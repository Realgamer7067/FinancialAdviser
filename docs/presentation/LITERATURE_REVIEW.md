# Literature review

**Project:** Financial Advisor. **Supervisor:** Dr. Jay Prakash Maurya. Primary papers/model documentation were checked for this presentation pack on 6 October 2026. This section explains the foundations of the implementation; published benchmark results are not this project's results.

## Research-to-implementation mapping

| Work | Main idea | Relationship to this project | Limitation relevant to our project |
|---|---|---|---|
| Harry Markowitz, **Portfolio Selection** (1952) | Portfolio selection considers return and covariance rather than isolated assets. | Background for the earlier PyPortfolioOpt mean-variance path. | Estimated returns/covariances and incomplete personal constraints can make an optimiser unsuitable without further checks. |
| Olivier Ledoit and Michael Wolf, **Honey, I Shrunk the Sample Covariance Matrix** (2004) | Shrink noisy sample covariance toward a structured target. | Background for current PyPortfolioOpt Ledoit–Wolf risk descriptions. | Better covariance estimation is not evidence of future-return prediction or correct personal suitability. |
| Doğu Aracı, **FinBERT: Financial Sentiment Analysis with Pre-trained Language Models** (2019) | Adapt pretrained language representations to financial sentiment. | Earlier adapter uses `ProsusAI/finbert` for financial text labels. | Sentiment classification does not establish later price direction; domain/task evaluation is still needed. |
| Yu Shi et al., **Kronos: A Foundation Model for the Language of Financial Markets** (2025) | Tokenise financial candlesticks and model their sequences autoregressively. | CPU integration uses Kronos-small/tokenizer to sample forecasts. | Paper benchmarks do not validate this local universe, sampling bands or investment policy. |
| Qwen Team, **Qwen2.5 Technical Report** (2024) | A family of pretrained/instruction-tuned language models for varied tasks. | Configurable Qwen-compatible structured-output provider for council/research/thesis assistance. | Fluent responses need source validation; provider/model access is an operational dependency. |
| John Schulman et al., **Proximal Policy Optimization Algorithms** (2017) | Policy-gradient learning using a clipped surrogate objective and repeated minibatch updates. | Background for the experimental Stable-Baselines3 PPO portfolio path. | A briefly trained policy/checkpoint does not establish robustness or realistic investment performance. |

## Primary references

1. Markowitz, H. (1952). *Portfolio Selection*. The Journal of Finance, 7(1), 77–91. [Publisher record and DOI](https://onlinelibrary.wiley.com/doi/full/10.1111/j.1540-6261.1952.tb01525.x).
2. Ledoit, O., & Wolf, M. (2004). *Honey, I Shrunk the Sample Covariance Matrix*. The Journal of Portfolio Management, 30(4), 110–119. [Author-hosted paper](https://ledoit.net/Honey_2004.pdf).
3. Aracı, D. (2019). *FinBERT: Financial Sentiment Analysis with Pre-trained Language Models*. [arXiv:1908.10063](https://arxiv.org/abs/1908.10063). [Model owner documentation](https://huggingface.co/ProsusAI/finbert).
4. Shi, Y., Fu, Z., Chen, S., Zhao, B., Xu, W., Zhang, C., & Li, J. (2025). *Kronos: A Foundation Model for the Language of Financial Markets*. [arXiv:2508.02739](https://arxiv.org/abs/2508.02739).
5. Qwen Team (2024). *Qwen2.5 Technical Report*. [arXiv:2412.15115](https://arxiv.org/abs/2412.15115).
6. Schulman, J., Wolski, F., Dhariwal, P., Radford, A., & Klimov, O. (2017). *Proximal Policy Optimization Algorithms*. [arXiv:1707.06347](https://arxiv.org/abs/1707.06347).

## Existing approaches and the integration gap

| Approach | Useful capability | Gap our proposed system addresses |
|---|---|---|
| Account-level holdings view | Shows a source account's positions | Separate accounts, completeness declaration and common state are needed |
| Spreadsheet/manual review | Flexible and inspectable | Repeated imports, revision binding and reproducible checks require discipline |
| Stateless SIP calculator | Explains contribution/return scenarios | Does not inherently bind to holdings, claims and reserve capacity |
| Isolated technical indicator | Describes price behaviour | Does not establish financial suitability or independent evidence |
| Standalone LLM answer | Flexible explanation | Unsupported factual claims and unsupported numerical conclusions need verification |
| Pure weight optimiser | Coordinates estimated asset risk/return | Goal claims, missing data, taxes and real purchase units require other layers |

This is an architectural comparison, not an independently benchmarked comparison of named commercial products. The project does not claim every broker or adviser tool lacks these features.

## Proposed novelty and boundary

Our novelty is the integrated workflow: account-scoped complete imports → a versioned twin → capacity/tolerance/goal constraints → covered risk → proposal/HOLD comparison → dated reasons and evidence. The financial algorithms and pretrained models are established prior work. We do not claim to have invented a foundation model, proved market outperformance or independently reproduced a paper's benchmark.

See [the formula reference](FORMULAS_LIBRARIES_MODELS.md) for code links and [the report](../../PROJECT_REPORT.md) for the full proposed methodology.
