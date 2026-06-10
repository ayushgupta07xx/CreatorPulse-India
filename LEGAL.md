# Legal & Data Use

CreatorPulse India sources data exclusively through the **official YouTube Data API v3**, used in accordance with the [YouTube API Services Terms of Service](https://developers.google.com/youtube/terms/api-services-terms-of-service) and the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy).

- **No scraping.** All channel and video data is retrieved through documented API endpoints under the project's API quota. No browser automation, no bot-wall circumvention, no residential proxies.
- **Public data only.** Only publicly available channel and video statistics are stored.
- **No commercial redistribution.** Data is used for analytics and screening within this application and is not resold or redistributed as a dataset.
- **Engagement-quality screening is a risk signal, not a verdict.** Scores are computed from public engagement patterns and heuristic rules; they are not platform-verified fraud determinations. See `docs/model_card.md`.
- **Earnings figures are estimates** of AdSense-equivalent revenue derived from public view counts and industry-standard CPMs — not actual creator income.
- **Instagram and other platforms** are out of scope for v1 and are not collected.

For data-removal requests, open an issue referencing the channel ID.

## Data attribution

The initial channel-discovery seed list draws in part from the open dataset
**"2024 YouTube Channels (1 Million)"** by asaniczka, published on Kaggle under the
Open Data Commons Attribution License (ODC-By 1.0):
https://www.kaggle.com/datasets/asaniczka/2024-youtube-channels-1-million

Only channel identifiers were used as discovery seeds. All channel and video
statistics in this product are fetched live from the YouTube Data API v3 and are
not derived from the source dataset.
