#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests>=2.32.0",
# ]
# ///
"""
JPDB Sentence Tool

Creates a JPDB deck from text and automatically sets custom sentences
for new vocabulary cards using the actual sentences from the source text.
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional

import requests

# JPDB API base URL
JPDB_API_BASE = "https://jpdb.io"

# Maximum characters per parse request (conservative limit based on testing)
# The actual limit appears to be somewhere between 5,500-6,000 characters.
# We use 5,000 to be safe.
MAX_PARSE_CHARS = 5000


@dataclass
class Vocabulary:
    """Represents a vocabulary item from JPDB."""
    vid: int
    sid: int
    spelling: str
    reading: str
    card_state: Optional[str]
    position: int  # Position in text (utf32 code points)
    length: int    # Length in text (utf32 code points)


class JPDBClient:
    """Client for interacting with the JPDB API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def _request(self, endpoint: str, data: dict) -> dict:
        """Make a POST request to the JPDB API."""
        url = f"{JPDB_API_BASE}{endpoint}"
        response = self.session.post(url, json=data)
        
        if response.status_code == 429:
            # Rate limited - wait and retry
            print("Rate limited, waiting 5 seconds...")
            time.sleep(5)
            response = self.session.post(url, json=data)
        
        if response.status_code not in (200, 201):
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("error_message", response.text)
            raise Exception(f"API error ({response.status_code}): {error_msg}")
        
        return response.json()

    def ping(self) -> bool:
        """Test if the API key is valid."""
        try:
            self._request("/api/v1/ping", {})
            return True
        except Exception:
            return False

    def _parse_chunk(self, text: str, position_offset: int = 0) -> list[Vocabulary]:
        """
        Parse a single chunk of Japanese text.
        
        Args:
            text: The text chunk to parse
            position_offset: Offset to add to all positions (for chunked parsing)
            
        Returns:
            List of Vocabulary objects with adjusted positions
        """
        data = {
            "text": text,
            "token_fields": ["vocabulary_index", "position", "length"],
            "vocabulary_fields": ["vid", "sid", "spelling", "reading", "card_state"],
            "position_length_encoding": "utf32",
        }
        
        result = self._request("/api/v1/parse", data)
        
        tokens = result.get("tokens", [])
        vocab_list = result.get("vocabulary", [])
        
        # Build vocabulary objects with position info from tokens
        vocabularies = []
        for token in tokens:
            vocab_idx, position, length = token[0], token[1], token[2]
            if vocab_idx < len(vocab_list):
                v = vocab_list[vocab_idx]
                vocabularies.append(Vocabulary(
                    vid=v[0],
                    sid=v[1],
                    spelling=v[2],
                    reading=v[3],
                    card_state=v[4] if len(v) > 4 else None,
                    position=position + position_offset,
                    length=length,
                ))
        
        return vocabularies

    def parse_text(self, text: str, verbose: bool = False, chunk_size: int = MAX_PARSE_CHARS) -> list[Vocabulary]:
        """
        Parse Japanese text and return vocabulary with position info.
        Automatically chunks large texts to stay within API limits.
        
        Args:
            text: The full text to parse
            verbose: Whether to print progress for chunked parsing
            chunk_size: Maximum characters per API request
            
        Returns:
            List of Vocabulary objects with positions relative to full text
        """
        # If text is small enough, parse directly
        if len(text) <= chunk_size:
            return self._parse_chunk(text)
        
        # Split into chunks at sentence boundaries
        chunks = chunk_text_by_sentences(text, chunk_size)
        
        if verbose:
            print(f"  Text too large, splitting into {len(chunks)} chunks...")
        
        all_vocabularies = []
        current_offset = 0
        
        for i, chunk in enumerate(chunks):
            if verbose:
                print(f"  Parsing chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)...")
            
            chunk_vocabs = self._parse_chunk(chunk, position_offset=current_offset)
            all_vocabularies.extend(chunk_vocabs)
            
            # Update offset for next chunk (in utf32 code points, which equals len() for Python strings)
            current_offset += len(chunk)
            
            # Small delay between chunks to avoid rate limiting
            if i < len(chunks) - 1:
                time.sleep(0.3)
        
        return all_vocabularies

    def create_deck(self, name: str) -> int:
        """Create a new empty deck and return its ID."""
        data = {"name": name}
        result = self._request("/api/v1/deck/create-empty", data)
        return result["id"]

    def add_vocabulary_to_deck(self, deck_id: int, vocabulary: list[tuple[int, int]]) -> None:
        """Add vocabulary to a deck. vocabulary is list of (vid, sid) tuples."""
        if not vocabulary:
            return
        
        data = {
            "id": deck_id,
            "vocabulary": vocabulary,
        }
        self._request("/api/v1/deck/add-vocabulary", data)

    def set_card_sentence(self, vid: int, sid: int, sentence: str, translation: Optional[str] = None) -> None:
        """Set a custom sentence for a vocabulary card."""
        data = {
            "vid": vid,
            "sid": sid,
            "sentence": sentence,
        }
        if translation:
            data["translation"] = translation
        
        self._request("/api/v1/set-card-sentence", data)


def chunk_text_by_sentences(text: str, max_chars: int) -> list[str]:
    """
    Split text into chunks at sentence boundaries, keeping each chunk under max_chars.
    
    Args:
        text: The full text to chunk
        max_chars: Maximum characters per chunk
        
    Returns:
        List of text chunks
    """
    # Japanese sentence-ending punctuation
    sentence_enders = r'[。！？\n]+'
    
    chunks = []
    current_chunk_start = 0
    last_sentence_end = 0
    
    for match in re.finditer(sentence_enders, text):
        sentence_end = match.end()
        
        # Check if adding this sentence would exceed the limit
        potential_chunk = text[current_chunk_start:sentence_end]
        
        if len(potential_chunk) > max_chars:
            # This chunk would be too big
            if last_sentence_end > current_chunk_start:
                # Save the chunk up to the previous sentence
                chunks.append(text[current_chunk_start:last_sentence_end])
                current_chunk_start = last_sentence_end
            else:
                # Single sentence is too long - we have to split it anyway
                # (This shouldn't happen often with reasonable max_chars)
                chunks.append(text[current_chunk_start:sentence_end])
                current_chunk_start = sentence_end
        
        last_sentence_end = sentence_end
    
    # Handle remaining text
    if current_chunk_start < len(text):
        remaining = text[current_chunk_start:]
        if remaining.strip():
            # If remaining is too long, split it (edge case)
            while len(remaining) > max_chars:
                chunks.append(remaining[:max_chars])
                remaining = remaining[max_chars:]
            if remaining.strip():
                chunks.append(remaining)
    
    return chunks


def split_into_sentences(text: str) -> list[tuple[str, int, int]]:
    """
    Split Japanese text into sentences.
    
    Returns list of (sentence, start_pos, end_pos) tuples.
    Positions are in utf32 code points.
    """
    # Japanese sentence-ending punctuation
    sentence_enders = r'[。！？\n]+'
    
    sentences = []
    current_pos = 0
    
    for match in re.finditer(sentence_enders, text):
        end_pos = match.end()
        sentence = text[current_pos:end_pos].strip()
        if sentence:
            # Calculate utf32 positions
            start_utf32 = len(text[:current_pos])
            end_utf32 = len(text[:end_pos])
            sentences.append((sentence, start_utf32, end_utf32))
        current_pos = end_pos
    
    # Handle remaining text (sentence without ending punctuation)
    if current_pos < len(text):
        sentence = text[current_pos:].strip()
        if sentence:
            start_utf32 = len(text[:current_pos])
            end_utf32 = len(text)
            sentences.append((sentence, start_utf32, end_utf32))
    
    return sentences


def find_sentence_for_position(sentences: list[tuple[str, int, int]], position: int) -> Optional[str]:
    """Find the sentence containing the given position."""
    for sentence, start, end in sentences:
        if start <= position < end:
            return sentence
    return None


def get_api_key() -> Optional[str]:
    """Get JPDB API key from environment or config."""
    # Try environment variable first
    api_key = os.environ.get("JPDB_API_KEY")
    if api_key:
        return api_key
    
    # Try config file in home directory
    config_path = os.path.expanduser("~/.jpdb_api_key")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return f.read().strip()
    
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Create a JPDB deck from text with custom sentences for new vocabulary.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.txt "My New Deck"
  %(prog)s --api-key YOUR_KEY input.txt "Anime Episode 1"
  
The API key can be provided via:
  - Command line: --api-key YOUR_KEY
  - Environment variable: JPDB_API_KEY
  - Config file: ~/.jpdb_api_key
  
Get your API key from: https://jpdb.io/settings#api-key
""",
    )
    
    parser.add_argument(
        "input_file",
        help="Path to the text file containing Japanese text",
    )
    parser.add_argument(
        "deck_name",
        help="Name for the new JPDB deck",
    )
    parser.add_argument(
        "--api-key",
        help="JPDB API key (or set JPDB_API_KEY env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse text and show what would be done without making changes",
    )
    parser.add_argument(
        "--all-words",
        action="store_true",
        help="Set sentences for all words, not just new ones",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show verbose output",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=MAX_PARSE_CHARS,
        help=f"Maximum characters per API parse request (default: {MAX_PARSE_CHARS})",
    )
    
    args = parser.parse_args()
    
    # Get API key
    api_key = args.api_key or get_api_key()
    if not api_key:
        print("Error: No API key provided.", file=sys.stderr)
        print("Provide via --api-key, JPDB_API_KEY env var, or ~/.jpdb_api_key", file=sys.stderr)
        sys.exit(1)
    
    # Read input file
    try:
        with open(args.input_file, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {args.input_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)
    
    if not text.strip():
        print("Error: Input file is empty.", file=sys.stderr)
        sys.exit(1)
    
    # Initialize client
    client = JPDBClient(api_key)
    
    # Test API key
    if not args.dry_run:
        print("Validating API key...")
        if not client.ping():
            print("Error: Invalid API key.", file=sys.stderr)
            sys.exit(1)
    
    # Parse the text
    print(f"Parsing text ({len(text)} characters)...")
    vocabularies = client.parse_text(text, verbose=args.verbose, chunk_size=args.chunk_size)
    print(f"Found {len(vocabularies)} tokens, {len(set((v.vid, v.sid) for v in vocabularies))} unique words")
    
    # Split text into sentences
    sentences = split_into_sentences(text)
    print(f"Split into {len(sentences)} sentences")
    
    # Find unique vocabulary with their first occurrence position
    # and map each to its containing sentence
    first_occurrences: dict[tuple[int, int], Vocabulary] = {}
    word_sentences: dict[tuple[int, int], str] = {}
    
    for vocab in vocabularies:
        key = (vocab.vid, vocab.sid)
        if key not in first_occurrences:
            first_occurrences[key] = vocab
            sentence = find_sentence_for_position(sentences, vocab.position)
            if sentence:
                word_sentences[key] = sentence
    
    # Identify new words (card_state is None means never seen before)
    new_words = [
        (key, vocab) for key, vocab in first_occurrences.items()
        if args.all_words or vocab.card_state is None
    ]
    
    status = "all" if args.all_words else "new"
    print(f"Found {len(new_words)} {status} words to set sentences for")
    
    if args.verbose:
        print("\nNew words and their sentences:")
        for key, vocab in new_words[:10]:  # Show first 10
            sentence = word_sentences.get(key, "(no sentence found)")
            print(f"  {vocab.spelling} ({vocab.reading}): {sentence[:50]}...")
        if len(new_words) > 10:
            print(f"  ... and {len(new_words) - 10} more")
    
    if args.dry_run:
        print("\n[Dry run - no changes made]")
        print(f"Would create deck: {args.deck_name}")
        print(f"Would add {len(first_occurrences)} vocabulary items")
        print(f"Would set {len(new_words)} custom sentences")
        return
    
    # Create the deck
    print(f"\nCreating deck: {args.deck_name}")
    deck_id = client.create_deck(args.deck_name)
    print(f"Created deck with ID: {deck_id}")
    
    # Add vocabulary to deck
    vocab_list = list(first_occurrences.keys())
    print(f"Adding {len(vocab_list)} vocabulary items to deck...")
    
    # Add in batches to avoid rate limits
    batch_size = 100
    for i in range(0, len(vocab_list), batch_size):
        batch = vocab_list[i:i + batch_size]
        client.add_vocabulary_to_deck(deck_id, batch)
        if args.verbose:
            print(f"  Added batch {i // batch_size + 1}/{(len(vocab_list) + batch_size - 1) // batch_size}")
    
    # Set custom sentences for new words
    print(f"Setting custom sentences for {len(new_words)} words...")
    
    success_count = 0
    error_count = 0
    
    for i, (key, vocab) in enumerate(new_words):
        sentence = word_sentences.get(key)
        if not sentence:
            if args.verbose:
                print(f"  Skipping {vocab.spelling}: no sentence found")
            continue
        
        try:
            client.set_card_sentence(vocab.vid, vocab.sid, sentence)
            success_count += 1
            if args.verbose:
                print(f"  [{i + 1}/{len(new_words)}] Set sentence for {vocab.spelling}")
        except Exception as e:
            error_count += 1
            if args.verbose:
                print(f"  [{i + 1}/{len(new_words)}] Error setting sentence for {vocab.spelling}: {e}")
        
        # Small delay to avoid rate limiting
        if (i + 1) % 10 == 0:
            time.sleep(0.5)
    
    print(f"\nDone!")
    print(f"  Deck created: {args.deck_name} (ID: {deck_id})")
    print(f"  Vocabulary added: {len(vocab_list)}")
    print(f"  Sentences set: {success_count}")
    if error_count > 0:
        print(f"  Errors: {error_count}")


if __name__ == "__main__":
    main()
