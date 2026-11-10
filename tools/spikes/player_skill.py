"""Spike: rate randomizer players from every hole score in a site database.

strokes = mu + par/distance/wind terms + skill[player] + layout[hole_id]
          + terrain[data_hash] + pin[data_hash, pin] + noise

The four bracketed groups are random effects, ridge-shrunk with penalties that EM
estimates from the data (lambda_g = sigma^2 / tau_g^2). Ratings are reported per 18
holes against the field and against stated par on an average live seed.

Experimental and unmaintained; see tools/spikes/README.md. Run with
`uv run python -m tools.spikes.player_skill <golf_site.db>`.
"""

import argparse
import sqlite3
from dataclasses import dataclass

import numpy as np

GROUPS = ("skill", "layout", "terrain", "pin")

PLAYED_SQL = """
select coalesce(u.global_name, u.username), sh.hole_id, sh.data_hash, sh.pin_index,
       sh.par, coalesce(sh.distance, 0), sh.wind_speed, rh.strokes
from round_holes rh
join rounds r on r.id = rh.round_id
join entries e on e.id = r.entry_id
join users u on u.id = e.user_id
join seed_holes sh on sh.seed_id = e.seed_id and sh.position = rh.position
"""

LIVE_SLOTS_SQL = """
select sh.seed_id, sh.hole_id, sh.data_hash, sh.pin_index, sh.par,
       coalesce(sh.distance, 0), sh.wind_speed
from seed_holes sh join seeds s on s.id = sh.seed_id
where s.withdrawn_at is null
"""


@dataclass
class Slot:
    """One hole as played: what the fixed and random effects are keyed on."""

    hole_id: str
    data_hash: str
    pin_index: int
    par: int
    distance: float
    wind_speed: float

    def key(self, group: str) -> str:
        if group == "layout":
            return self.hole_id
        if group == "terrain":
            return self.data_hash
        return f"{self.data_hash}:{self.pin_index}"


@dataclass
class Fit:
    beta: np.ndarray
    cov: np.ndarray
    sigma: float
    lams: dict[str, float]
    blocks: dict[str, tuple[int, int]]
    levels: dict[str, list[str]]
    distance_mean: float
    iterations: int
    converged: bool


def fixed_columns(slots: list[Slot], distance_mean: float) -> np.ndarray:
    par = np.array([s.par for s in slots])
    dist = np.array([s.distance for s in slots], float)
    wind = np.array([s.wind_speed for s in slots], float)
    return np.column_stack(
        [np.ones(len(slots)), par == 4, par == 5, (dist - distance_mean) / 100, wind]
    ).astype(float)


def fit(players: list[str], slots: list[Slot], y: np.ndarray, max_iter: int) -> Fit:
    n = len(slots)
    keys = {"skill": players} | {
        g: [s.key(g) for s in slots] for g in GROUPS if g != "skill"
    }
    levels = {g: sorted(set(keys[g])) for g in GROUPS}
    distance_mean = float(np.mean([s.distance for s in slots]))
    cols = [fixed_columns(slots, distance_mean)]
    blocks: dict[str, tuple[int, int]] = {}
    off = cols[0].shape[1]
    for g in GROUPS:
        idx = {v: i for i, v in enumerate(levels[g])}
        m = np.zeros((n, len(idx)))
        m[np.arange(n), [idx[v] for v in keys[g]]] = 1
        cols.append(m)
        blocks[g] = (off, off + len(idx))
        off += len(idx)
    x = np.hstack(cols)
    xtx, xty = x.T @ x, x.T @ y

    def solve(lams: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
        pen = np.zeros(x.shape[1])
        for g, (a, b) in blocks.items():
            pen[a:b] = lams[g]
        a_mat = xtx + np.diag(pen)
        return np.linalg.solve(a_mat, xty), a_mat

    # EM for the variance components: tau_g^2 adds back the spread shrinkage hid.
    lams: dict[str, float] = dict.fromkeys(GROUPS, 10.0)
    converged = False
    iterations = 0
    while not converged and iterations < max_iter:
        iterations += 1
        beta, a_mat = solve(lams)
        res = y - x @ beta
        a_inv = np.linalg.inv(a_mat)
        sig2 = float(res @ res) / n
        new: dict[str, float] = {}
        for g, (a, b) in blocks.items():
            u = beta[a:b]
            tau2 = (u @ u + sig2 * np.trace(a_inv[a:b, a:b])) / (b - a)
            new[g] = min(sig2 / max(tau2, 1e-9), 1e6)
        converged = all(abs(np.log(new[g] / lams[g])) < 1e-4 for g in GROUPS)
        lams = new

    beta, a_mat = solve(lams)
    sigma = float((y - x @ beta).std(ddof=1))
    return Fit(
        beta=beta,
        cov=sigma**2 * np.linalg.inv(a_mat),
        sigma=sigma,
        lams=lams,
        blocks=blocks,
        levels=levels,
        distance_mean=distance_mean,
        iterations=iterations,
        converged=converged,
    )


def par_offset(model: Fit, live: list[tuple[str, Slot]]) -> tuple[int, float, float]:
    """The field-average player's expected score vs stated par on an average live seed."""
    slots = [s for _, s in live]
    fixed = fixed_columns(slots, model.distance_mean)
    pred = fixed @ model.beta[: fixed.shape[1]]
    for g in GROUPS[1:]:
        a, _ = model.blocks[g]
        idx = {v: i for i, v in enumerate(model.levels[g])}
        pred += np.array(
            [model.beta[a + idx[s.key(g)]] if s.key(g) in idx else 0.0 for s in slots]
        )
    par = np.array([s.par for s in slots])
    nseeds = len({seed for seed, _ in live})
    return nseeds, float(par.sum() / nseeds), float((pred - par).sum() / nseeds)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Rate randomizer players from a site database (spike)."
    )
    parser.add_argument("db", help="a randomizer site database (golf_site.db)")
    parser.add_argument(
        "--max-iter", type=int, default=500, help="EM iteration cap (default 500)"
    )
    args = parser.parse_args(argv)

    db = sqlite3.connect(args.db)
    played = db.execute(PLAYED_SQL).fetchall()
    players = [r[0] for r in played]
    slots = [Slot(r[1], r[2], r[3], r[4], r[5], r[6]) for r in played]
    y = np.array([r[7] for r in played], float)
    over = y - np.array([s.par for s in slots])
    nrounds = db.execute("select count(*) from rounds").fetchone()[0]
    print(
        f"rounds {nrounds}, hole scores {len(y)}; strokes vs par: mean "
        f"{over.mean():+.2f}, sd {over.std():.2f}, worst {over.max():+.0f}, "
        f"+3 or worse {(over >= 3).mean():.1%}"
    )

    model = fit(players, slots, y, args.max_iter)
    status = "converged" if model.converged else "hit the cap"
    print(f"EM: {model.iterations} iterations ({status})")
    print("spread per hole (tau):")
    for g in GROUPS:
        tau = (model.sigma**2 / model.lams[g]) ** 0.5
        print(f"  {g:8} {tau:.3f}  ({len(model.levels[g])} levels)")
    print(f"  {'luck':8} {model.sigma:.3f}  (residual)")
    b = model.beta
    print(
        f"fixed: par4 {b[1]:+.2f}, par5 {b[2]:+.2f}, per 100 yd {b[3]:+.3f}, "
        f"per wind unit {b[4]:+.3f}"
    )

    live = [
        (r[0], Slot(r[1], r[2], r[3], r[4], r[5], r[6]))
        for r in db.execute(LIVE_SLOTS_SQL).fetchall()
    ]
    nseeds, mean_par, offset = par_offset(model, live)
    print(
        f"\n{nseeds} live seeds, mean par {mean_par:.1f}; field-average player "
        f"{offset:+.1f} vs par"
    )

    a, z = model.blocks["skill"]
    skill = model.beta[a:z]
    k = z - a
    center = np.eye(k) - 1 / k
    se = np.sqrt(np.diag(center @ model.cov[a:z, a:z] @ center.T))
    rel = skill - skill.mean()
    holes = {p: players.count(p) for p in model.levels["skill"]}
    raw = {
        p: 18 * float(np.mean(over[[q == p for q in players]]))
        for p in model.levels["skill"]
    }
    print(
        f"\n{'player':26}{'holes':>6}{'vs field':>9}{'vs par':>8}{'se':>6}"
        f"{'raw vs par':>11}   (per 18 holes)"
    )
    for i in np.argsort(rel):
        p = model.levels["skill"][i]
        print(
            f"{p:26}{holes[p]:>6}{18 * rel[i]:>+9.1f}{offset + 18 * rel[i]:>+8.1f}"
            f"{18 * se[i]:>6.1f}{raw[p]:>+11.1f}"
        )


if __name__ == "__main__":
    main()
