# bfe-emob
A scraper for the BFE e-mobility data


## Usage

This repo downloads the latest data from the e-mobility service and saves it as a JSON file in the `data` directory.
The history is therefore saved in the git history.

If you need the full history as a file, you can extract it from the git history with the following command:

```
uv run extract_git_history.py -i data\ch.bfe.ladestellen-elektromobilitaet_de.json -o emob_history.jsonl --start-at 7d398e70718a3f519230aa35ee4dc6a75faf5be2
```

Note: this generates a large [JSON Lines](https://jsonlines.org/) `emob_history.jsonl` file, where each line is one history entry.
