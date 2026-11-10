# Lessons

- **Prices from scraped pages: use only one labelled field, and cross-check.** (2026-11-10) I quoted
  `g6e.4xlarge` at $1.98/h; the on-demand price is $3.00/h. The $1.98 came from an
  unlabelled number in an instances.vantage.sh scrape (spot or reserved), which I had
  already seen was wrong for other instances but did not re-fetch for this one. Rule: take
  the on-demand price only from the page's "starting at $X per hour" line, fetch it for
  every instance I quote, and cross-check with Coiled's "Approx cloud cost" when a VM
  launches.
