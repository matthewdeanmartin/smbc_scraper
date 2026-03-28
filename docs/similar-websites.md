# Similar websites

These are the main websites around SMBC that matter when using or extending this
repo.

## Official SMBC site

- <https://www.smbc-comics.com>

This is the canonical source for comic pages, main images, votey panels, page
titles, and hover text. The `smbc`, `smbc-all`, `smbc-update`, and
`smbc-images` workflows all revolve around the official site.

## SMBC Wiki

- <https://www.smbc-wiki.com/>

The wiki is useful for transcript-style text and community-maintained metadata.
This repo's `wiki` command queries the MediaWiki API rather than scraping the
visible site pages.

## Oh No Robot

- <https://www.ohnorobot.com/index.php?comic=137>

Oh No Robot is primarily a search experience over comic transcripts. In this
repo it acts as a complementary enrichment source, especially when you already
have titles or page metadata from another export.

## Community-maintained datasets

- <https://docs.google.com/spreadsheets/d/1CH3NX_xKOx-VIPZqp5GkCTHdS7QDsmg7w9Q71Z-aRT0/edit?gid=0#gid=0>
- <https://github.com/fricklerhandwerk/smbc>

These are not websites you scrape through the main CLI today, but they matter as
adjacent source material, cross-checking material, and ecosystem context.

## Why these matter together

No single site captures every useful view of SMBC data:

- the official site is best for canonical pages and images
- the wiki is best for structured transcripts and community notes
- Oh No Robot is best for search-style discovery
- community datasets help with comparison and recovery work

That is why this repo is organized as a multi-source scraper instead of a single
"download the comic image" script.
