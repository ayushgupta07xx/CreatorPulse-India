"""Simulated-cohort Bayesian analysis for the match_rerank_v2 A/B test.

CreatorPulse has no organic traffic, so this is NOT a live experiment result.
It is a SIMULATED cohort that poses a real learning problem (per-session Bernoulli
shortlist outcomes with injected, calibrated base rates), analysed with a
Beta-Binomial conjugate model. The figure it produces is the only basis for the
"~23% lift @96%" claim, which stays labeled SIMULATED/TARGET until real PostHog
events replace it. PostHog's native experiment view computes the same posterior
once `shortlist_addition_rate` events flow.

Run from repo root:  python analysis/ab_match_rerank.py
"""

from __future__ import annotations

import numpy as np

SEED = 6
N_PER_ARM = 1000  # powered to recover the injected lift; report the 96% credible interval
P_CONTROL = 0.300  # Variant A: pure Stage-1 cosine ranking
P_TEST = 0.369  # Variant B: full two-stage rerank -> +23% true relative lift
PRIOR_A, PRIOR_B = 1.0, 1.0  # uniform Beta(1, 1) prior per arm
DRAWS = 200_000
CRED = 0.96  # credible-interval mass / decision threshold


def main() -> None:
    rng = np.random.default_rng(SEED)
    ctrl = rng.binomial(1, P_CONTROL, N_PER_ARM)
    test = rng.binomial(1, P_TEST, N_PER_ARM)

    post_ctrl = rng.beta(PRIOR_A + ctrl.sum(), PRIOR_B + (N_PER_ARM - ctrl.sum()), DRAWS)
    post_test = rng.beta(PRIOR_A + test.sum(), PRIOR_B + (N_PER_ARM - test.sum()), DRAWS)
    rel_lift = (post_test - post_ctrl) / post_ctrl

    p_better = float((post_test > post_ctrl).mean())
    lo = float(np.quantile(rel_lift, (1 - CRED) / 2))
    hi = float(np.quantile(rel_lift, 1 - (1 - CRED) / 2))

    print(f"Variant A (control) shortlist rate: {ctrl.mean():.3f}  (n={N_PER_ARM})")
    print(f"Variant B (test)    shortlist rate: {test.mean():.3f}  (n={N_PER_ARM})")
    print(f"Posterior mean relative lift:       {rel_lift.mean() * 100:.1f}%")
    print(f"{int(CRED * 100)}% credible interval on lift:    [{lo * 100:.1f}%, {hi * 100:.1f}%]")
    print(f"P(B > A):                           {p_better:.3f}")


if __name__ == "__main__":
    main()
