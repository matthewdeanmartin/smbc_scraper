# Prior art

This file keeps the original project link list, but with a little structure and
commentary so it is useful as working context instead of just a scratchpad.

The goal is not to claim that every link is a direct dependency. Some are
datasets, some are search tools, some are viewers, and some are projects that
show how people have reused or extended SMBC material.

## Full datasets and mirrors

- <https://github.com/fricklerhandwerk/smbc>

This is the "that GitHub repo" dataset mentioned in the root README. In this
repo it remains adjacent source material rather than a first-class CLI command;
`smbc_scraper\sources\that_github_repo.py` is the direct-run helper for parsing
that style of markdown content.

## Download-all and scraper projects

- <https://github.com/sankalp-sangle/SMBC-Download>
- <https://github.com/baisakhic/smbc-comic-downloader>
- <https://github.com/HiiYL/smbc-comics-downloader> - Ruby implementation
- <https://github.com/chadharaghav/comic-scraper>

These projects are useful comparison points for archive downloading, image
fetching, and project scope. They mostly focus on "get every comic locally,"
while this repo also tries to normalize data into repeatable exports, keep raw
HTML, and support enrichment flows like wiki transcripts, Oh No Robot snippets,
and OCR output.

## Search engines and community lookup tools

- <https://vikramkashyap.com/smbc_search.php>
- <https://www.ohnorobot.com/index.php?comic=137>
- <https://smbc-wiki.com/index.php/Main_Page>

These sites matter because they solve adjacent problems:

- search by phrase or remembered snippet
- crowd-maintained transcript and metadata discovery
- alternate ways to find a comic when the official archive alone is not enough

In practice, this repo uses the same ecosystem for enrichment:

- `wiki` pulls transcript-oriented data from `smbc-wiki.com`
- `ohnorobot` uses existing exports to generate queries against Oh No Robot

## RSS, wallpaper, and viewer projects

- <https://github.com/smbc-rss-plus/smbc-rss-plus>
- <https://github.com/swopnilnep/smbc>
- <https://github.com/firebluetom/React-Native-SMBC-Comics>
- <https://github.com/mina86/emotional-hacking/tree/master> - includes display
  and aspect-ratio experimentation

These show another class of prior art: once people have reliable comic URLs and
images, they build readers, feeds, or custom presentation layers. That is a
helpful reminder that this repo's exports are not only for scraping, but also
for downstream browsing, indexing, and accessibility work.

## Projects inspired by SMBC

- <https://github.com/OpenBagTwo/MarketWatch>
- <https://github.com/Zirak/ConceptionConnection>
- <https://github.com/TomJB1/news-and-stocks-fun>
- <https://github.com/actozzo/FreedomNurbler>
- <https://github.com/likuilin/ticktacktoek>
- <https://github.com/rbarghou/django-kriegspiel-tick-tac-toe>
- <https://github.com/adamisom/smbc-fourier>
- <https://github.com/mikemxm/centimeter-encoding>

This last bucket is intentionally broad. Not every project here is a scraper or
dataset. The value is that it shows the wider "things people built because of
SMBC" landscape, which is useful when thinking about downstream consumers,
research directions, or fun side quests.

## How this repo differs

Compared with the links above, `smbc_scraper` currently emphasizes:

- multiple upstreams instead of a single source
- normalized tabular exports in `out\`
- preserved HTML and image assets in `data\`
- incremental updates via `out\smbc_ground_truth_state.json`
- optional OCR and accessibility descriptions for saved images
