# JPDB Sentence Tool

A CLI tool that creates JPDB decks from Japanese text and automatically sets custom sentences for new vocabulary cards using the actual sentences from the source text.

## The Problem

When creating a new deck from text on JPDB, the vocabulary cards get assigned random example sentences from JPDB's database rather than using the actual sentence from your source text. This tool fixes that by:

1. Parsing your Japanese text through JPDB's API
2. Creating a new deck with all the vocabulary
3. Setting each new word's custom sentence to the actual sentence it appeared in

## Installation & Running with uv

The simplest way to run this tool is with [uv](https://docs.astral.sh/uv/), which handles dependencies automatically:

```bash
# Run directly (uv will handle dependencies)
uv run jpdb_sentence_tool.py input.txt "My Deck Name"

# Or with explicit dependency
uv run --with requests jpdb_sentence_tool.py input.txt "My Deck Name"
```

### Alternative: Traditional pip install

```bash
pip install -r requirements.txt
python jpdb_sentence_tool.py input.txt "My Deck Name"
```

## Getting Your API Key

1. Go to https://jpdb.io/settings#api-key
2. Copy your API key

## Configuration

Provide your API key via one of these methods (in order of precedence):

1. **Command line argument**: `--api-key YOUR_KEY`
2. **Environment variable**: `export JPDB_API_KEY=YOUR_KEY`
3. **Config file**: Save your key to `~/.jpdb_api_key`

## Usage

```bash
# Basic usage
uv run jpdb_sentence_tool.py input.txt "My New Deck"

# With explicit API key
uv run jpdb_sentence_tool.py --api-key YOUR_KEY input.txt "Anime Episode 1"

# Dry run (see what would happen without making changes)
uv run jpdb_sentence_tool.py --dry-run input.txt "Test Deck"

# Set sentences for ALL words (not just new ones)
uv run jpdb_sentence_tool.py --all-words input.txt "Full Deck"

# Verbose output
uv run jpdb_sentence_tool.py -v input.txt "Verbose Deck"
```

## Options

| Option | Description |
|--------|-------------|
| `input_file` | Path to the text file containing Japanese text |
| `deck_name` | Name for the new JPDB deck |
| `--api-key` | JPDB API key (optional if set via env/config) |
| `--dry-run` | Parse text and show what would be done without making changes |
| `--all-words` | Set sentences for all words, not just new/unseen ones |
| `-v, --verbose` | Show detailed progress output |
| `--chunk-size` | Maximum characters per API parse request (default: 5000) |

## How It Works

1. **Parse text**: The tool sends your text to JPDB's `/api/v1/parse` endpoint, which tokenizes the Japanese and returns vocabulary information including each word's `vid` (vocabulary ID), `sid` (spelling ID), and `card_state`.

2. **Split sentences**: The text is split into sentences based on Japanese punctuation (。！？ and newlines).

3. **Map words to sentences**: For each unique word, the tool finds the sentence containing its first occurrence.

4. **Create deck**: A new empty deck is created via the API.

5. **Add vocabulary**: All unique vocabulary is added to the deck.

6. **Set sentences**: For each "new" word (one you haven't studied before on JPDB), the tool calls `/api/v1/set-card-sentence` with the actual sentence from your source text.

## Example

Input file (`episode1.txt`):
```
今日は天気がいいね。
明日も晴れるといいな。
```

```bash
$ uv run jpdb_sentence_tool.py episode1.txt "Episode 1"

Validating API key...
Parsing text (32 characters)...
Found 12 tokens, 10 unique words
Split into 2 sentences
Found 3 new words to set sentences for

Creating deck: Episode 1
Created deck with ID: 12345
Adding 10 vocabulary items to deck...
Setting custom sentences for 3 words...

Done!
  Deck created: Episode 1 (ID: 12345)
  Vocabulary added: 10
  Sentences set: 3
```

Now when you study the card for a new word like 天気, it will show "今日は天気がいいね。" as the example sentence instead of a random one from JPDB's database.

## Notes

- **Large text handling**: The JPDB parse API has an undocumented character limit (appears to be ~5,500-6,000 characters). This tool automatically chunks larger texts at sentence boundaries, parsing each chunk separately while maintaining correct position tracking. The default chunk size is 5,000 characters to stay safely under the limit.

- **Rate limiting**: The tool includes small delays to avoid hitting JPDB's rate limits. If you hit rate limits, it will wait and retry.

- **New words only**: By default, only "new" words (those you've never seen/studied) get custom sentences. Use `--all-words` to set sentences for all vocabulary.

- **Sentence detection**: The tool splits on 。！？ and newlines. If your text uses different sentence boundaries, you may want to preprocess it.

- **Word matching**: JPDB's API validates that the word actually appears in the sentence you're setting. If for some reason the match fails, you'll see an error in verbose mode.

- **Sentence length limit**: JPDB's custom sentence API has an undocumented length limit (under 108 characters). Longer sentences will fail with a "sentence is too long" error. Additionally, some conjugated verbs may fail validation if JPDB can't match the dictionary form to the conjugated form in the sentence.

## License

MIT
