# ClaimLens

Medical paperwork that crosses borders — in both directions.

ClaimLens reads hospital bills and medical certificates for people whose care crosses a border
(Koreans treated abroad, foreigners treated in Korea). When a Korean policy applies, it prepares a
claim decision with the cited policy clauses. When no policy applies, it does not decide — it builds
an English claim pack the person can take to their own insurer.

Built for the **Meta Global AI Developer Hackathon** (Indie track, Oct 27 – Nov 4, 2026).
All documents used in this repository are **synthetic**. ClaimLens processes insurance paperwork;
it does not give medical advice.

## What was built during the hackathon

Everything in this repository was written during the hackathon, starting from the first commit
on 2026-10-27 (KST). The table below is kept up to date as work lands.

| Built during the hackathon (this repo) | Pre-existing (dependency, not showcased) |
|---|---|
| _in progress_ | [clausegraph](https://github.com/JAEHUN-AN/clausegraph) — the author's MIT-licensed policy knowledge graph and adjudication engine, pinned to tag [`claimlens-base-20261026`](https://github.com/JAEHUN-AN/clausegraph/releases/tag/claimlens-base-20261026), created before the hackathon started |

Using a pre-existing open-source dependency was confirmed as acceptable in the hackathon Discord
(#questions, 2026-10-26).

## License

MIT — see [LICENSE](LICENSE).
