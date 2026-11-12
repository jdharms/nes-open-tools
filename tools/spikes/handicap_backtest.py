"""Spike: backtest handicapped formats on a site database's rounds.

Fits the hole model of `player_skill.py` with a skill x difficulty interaction, gives
each round a handicap from the player's earlier rounds on other seeds, and scores every
pair of players on every shared seed under several handicap schemes: match play, net
stroke play, net Stableford and skins. It also measures how fast a new rating settles,
what a thrown round moves, and simulates 28-day seasons. The results are written up in
`docs/competitive/design.md`.

Experimental and unmaintained; see tools/spikes/README.md. Run with
`uv run python -m tools.spikes.handicap_backtest <golf_site.db>`; it takes a few minutes.
"""

import argparse
import itertools
import sqlite3
from collections import defaultdict
from datetime import datetime

import numpy as np

# sigma^2 / tau^2 from the EM fit of player_skill.py on the 2026-11-10 database
LAM = {"skill": 1.39, "layout": 12.5, "terrain": 16.6, "pin": 112.0}


def run(db: str, min_holes: int) -> None:
    rows = (
        sqlite3.connect(db)
        .execute("""
    select coalesce(u.global_name,u.username), e.seed_id, r.id, r.received_at, rh.position,
           sh.hole_id, sh.data_hash, sh.pin_index, sh.par, coalesce(sh.distance,0),
           sh.wind_speed, rh.strokes
    from round_holes rh join rounds r on r.id=rh.round_id and r.slot=0
    join entries e on e.id=r.entry_id join users u on u.id=e.user_id
    join seed_holes sh on sh.seed_id=e.seed_id and sh.position=rh.position
    order by r.received_at, r.id, rh.position""")
        .fetchall()
    )

    n = len(rows)
    player = np.array([r[0] for r in rows])
    seed = np.array([r[1] for r in rows])
    rid = np.array([r[2] for r in rows])
    when = np.array([r[3] for r in rows])
    pos = np.array([r[4] for r in rows])
    par = np.array([r[8] for r in rows])
    dist = np.array([r[9] for r in rows], float)
    wind = np.array([r[10] for r in rows], float)
    y = np.array([r[11] for r in rows], float)
    keys = {
        "layout": [r[5] for r in rows],
        "terrain": [r[6] for r in rows],
        "pin": [f"{r[6]}:{r[7]}" for r in rows],
    }
    players = sorted(set(player))
    pidx = np.array([players.index(p) for p in player])
    dist_mean = dist.mean()
    fixed = np.column_stack(
        [np.ones(n), par == 4, par == 5, (dist - dist_mean) / 100, wind]
    ).astype(float)
    cols, pen = [fixed], [np.full(5, 1e-6)]
    for g in ("layout", "terrain", "pin"):
        lv = {v: i for i, v in enumerate(sorted(set(keys[g])))}
        m = np.zeros((n, len(lv)))
        m[np.arange(n), [lv[v] for v in keys[g]]] = 1
        cols.append(m)
        pen.append(np.full(len(lv), LAM[g]))
    hole_x = np.hstack(cols)  # hole-side design
    penalty = np.concatenate(pen)
    n_players = len(players)

    def fit(mask, gamma, iters=6):
        """Return (a, s): hole expectation for every row, skill per player.

        strokes = a_h + (1 + gamma*(a_h - abar)) * s_p ; gamma=0 is the additive model.
        """
        hole_m, ym, pm = hole_x[mask], y[mask], pidx[mask]
        s = np.zeros(n_players)
        abar = ym.mean()
        beta = None
        for _ in range(iters):
            w = 1 + gamma * s[pm]
            scaled = hole_m * w[:, None]
            beta = np.linalg.solve(
                scaled.T @ scaled + np.diag(penalty),
                scaled.T @ (ym - s[pm] * (1 - gamma * abar)),
            )
            a = hole_m @ beta
            abar = a.mean()
            b = 1 + gamma * (a - abar)
            num = np.bincount(pm, b * (ym - a), n_players)
            den = np.bincount(pm, b * b, n_players) + LAM["skill"]
            s = num / den
            s -= 0  # zero = shrinkage target (field mean)
        return hole_x @ beta, abar, s

    def fit_gamma():
        mask = np.ones(n, bool)
        gamma = 0.0
        a, abar, s = fit(mask, gamma, iters=3)
        for _ in range(25):
            z = s[pidx] * (a - abar)
            gamma = float(z @ (y - a - s[pidx]) / (z @ z))
            a, abar, s = fit(mask, gamma, iters=3)
        return gamma, a, abar, s

    gamma, a_all, abar_all, s_all = fit_gamma()
    print(
        f"rows {n}, players {n_players}; gamma {gamma:.3f}, abar {abar_all:.2f}, gamma*abar {gamma * abar_all:.2f}"
    )
    a0, _, s0 = fit(np.ones(n, bool), 0.0)
    print(
        f"in-sample resid sd: additive {(y - a0 - s0[pidx]).std():.4f}  interaction "
        f"{(y - a_all - (1 + gamma * (a_all - abar_all)) * s_all[pidx]).std():.4f}"
    )
    print("\nfull-data skill (strokes/18 vs field-mean player), additive | interaction")
    for i in np.argsort(s_all):
        print(
            f"  {players[i]:26}{18 * s0[i]:+7.1f}{18 * s_all[i]:+7.1f}   holes {int((pidx == i).sum())}"
        )

    # ---- predictions: hole side from every other seed, skill from the player's rounds
    # received before this round (a handicap "as of" the round)
    days = np.array(
        [
            datetime.fromisoformat(w.replace("Z", "+00:00")).timestamp() / 86400
            for w in when
        ]
    )
    rec = {"hl10": 10.0, "last8": None, "b8": None}
    pred = {m: np.full(n, np.nan) for m in ("add", "int", *rec)}
    diff = {m: np.full(n, np.nan) for m in ("add", "int")}  # a_h, for stroke index
    prior_holes = np.zeros(n)
    for sd in dict.fromkeys(seed):
        train = seed != sd
        test = seed == sd
        a0, _, _ = fit(train, 0.0)
        a, abar, _ = fit(train, gamma)
        b = 1 + gamma * (a - abar)
        diff["add"][test], diff["int"][test] = a0[test], a[test]
        for r in dict.fromkeys(rid[test]):
            tr = rid == r
            p, t = pidx[tr][0], days[tr][0]
            prior = train & (pidx == p) & (days < t)
            prior_holes[tr] = prior.sum()
            if not prior.any():
                continue
            pred["add"][tr] = a0[tr] + (y[prior] - a0[prior]).sum() / (
                prior.sum() + LAM["skill"]
            )

            def skill_of(w, a=a, b=b, prior=prior):
                num = (w * b * (y - a))[prior].sum()
                return num / ((w * b * b)[prior].sum() + LAM["skill"])

            pred["int"][tr] = a[tr] + b[tr] * skill_of(np.ones(n))
            pred["hl10"][tr] = a[tr] + b[tr] * skill_of(0.5 ** ((t - days) / 10.0))
            rr = list(dict.fromkeys(rid[prior]))
            pred["last8"][tr] = a[tr] + b[tr] * skill_of(
                np.isin(rid, rr[-8:]).astype(float)
            )
            per = sorted(
                (b * (y - a))[rid == q].sum() / (b * b)[rid == q].sum()
                for q in rr[-20:]
            )
            pred["b8"][tr] = a[tr] + b[tr] * np.mean(
                per[: max(1, round(0.4 * len(per)))]
            )

    # ---- round-level table
    rounds = []
    for r in dict.fromkeys(rid):
        ix = np.where(rid == r)[0]
        ix = ix[np.argsort(pos[ix])]
        if len(ix) != 18 or np.isnan(pred["add"][ix[0]]):
            continue
        rounds.append(
            dict(
                ix=ix,
                player=player[ix[0]],
                seed=seed[ix[0]],
                par=par[ix],
                y=y[ix],
                prior=prior_holes[ix[0]],
                **{f"p_{m}": pred[m][ix] for m in pred},
                **{f"d_{m}": diff[m][ix] for m in diff},
            )
        )
    print(f"\nrounds with a prequential prediction: {len(rounds)}")
    elig = [r for r in rounds if r["prior"] >= min_holes]
    print(f"  of which player had >= {min_holes} prior holes: {len(elig)}")

    print("\n== A. calibration of round totals (out of sample, eligible rounds)")
    for m in pred:
        e = np.array([r["y"].sum() - r[f"p_{m}"].sum() for r in elig])
        print(
            f"  {m}: bias {e.mean():+.2f}  rmse {np.sqrt((e**2).mean()):.2f}  mae {abs(e).mean():.2f}"
        )
    # error vs seed difficulty x skill
    sk = np.array([s_all[players.index(r["player"])] * 18 for r in elig])
    dfc = np.array([(r["d_add"] - r["par"]).sum() for r in elig])
    for m in ("add", "int"):
        e = np.array([r["y"].sum() - r[f"p_{m}"].sum() for r in elig])
        z = (sk - sk.mean()) * (dfc - dfc.mean())
        print(
            f"  {m}: error slope on skill x seed-difficulty: {float(z @ e / (z @ z)):+.4f}"
            f"   corr {np.corrcoef(z, e)[0, 1]:+.2f}"
        )
    print("  additive error by (player strength, seed difficulty tercile):")
    terc = np.digitize(dfc, np.quantile(dfc, [1 / 3, 2 / 3]))
    e = np.array([r["y"].sum() - r["p_add"].sum() for r in elig])
    e2 = np.array([r["y"].sum() - r["p_int"].sum() for r in elig])
    for lab, sel in (
        ("strong (skill<-5)", sk < -5),
        ("middle", (sk >= -5) & (sk < 5)),
        ("weak (>=+5)", sk >= 5),
    ):
        print(
            f"    {lab:18}"
            + "  ".join(
                f"{['easy', 'mid', 'hard'][t]}: add {e[sel & (terc == t)].mean():+5.1f} int {e2[sel & (terc == t)].mean():+5.1f} (n={int((sel & (terc == t)).sum())})"
                for t in range(3)
            )
        )

    # ---- handicap schemes
    def allocate(ch, order):
        """Strokes per hole for course handicap ch; order = hole indexes, hardest first."""
        out = np.zeros(18, int)
        if ch >= 0:
            q, rem = divmod(ch, 18)
            out += q
            out[order[:rem]] += 1
        else:
            q, rem = divmod(-ch, 18)
            out -= q
            out[order[::-1][:rem]] -= 1
        return out

    by_seed = defaultdict(list)
    for r in elig:
        by_seed[r["seed"]].append(r)
    # flat index: additive skill as of the seed, vs par on an "average" seed -> use mean over
    # all eligible rounds of that player's additive (pred - par) is leakage; instead flat =
    # 18*s + constant, and constants cancel in pairwise formats. Use field offset 10.4.
    offset = float(np.mean([(r["d_add"] - r["par"]).sum() for r in rounds]))
    for r in elig:
        sflat = (r["p_add"] - r["d_add"]).sum()  # 18 * additive skill as of this seed
        order = np.argsort(-r["d_int"], kind="stable")
        r["order"] = order
        r["ch"] = {
            "gross": 0,
            "flat": int(round(offset + sflat)),
            "whs": int(round((r["p_add"] - r["par"]).sum())),
            "day": int(round((r["p_int"] - r["par"]).sum())),
            **{m: int(round((r[f"p_{m}"] - r["par"]).sum())) for m in rec},
        }
        for al in (90, 80, 70):
            r["ch"][f"l8@{al}"] = int(round(al / 100 * r["ch"]["last8"]))
        r["net"] = {k: r["y"] - allocate(v, order) for k, v in r["ch"].items()}
        # exact: personal par per hole, fractional (upper bound on what handicapping can do)
        r["net"]["exact"] = r["y"] - (r["p_int"] - r["par"])
        r["ch"]["exact"] = r["ch"]["day"]

    schemes = (
        "gross",
        "flat",
        "day",
        "hl10",
        "last8",
        "b8",
        "l8@90",
        "l8@80",
        "l8@70",
        "exact",
    )
    strength = {p: 18 * s_all[i] for i, p in enumerate(players)}

    def pct(vals, lower_better=True):
        """Finishing percentile for each entry: 1 = beat everyone, 0.5 = tie/fair."""
        v = np.array(vals, float)
        if not lower_better:
            v = -v
        k = len(v)
        return [
            (float((v > x).sum()) + 0.5 * float((v == x).sum() - 1)) / (k - 1)
            for x in v
        ]

    def stableford(r, k):
        return np.maximum(0, 2 - (r["net"][k] - r["par"])).sum()

    def match(r1, r2, k):
        """Holes won by r1 minus holes won by r2, strokes given on the difference."""
        d = r1["ch"][k] - r2["ch"][k]
        if k == "exact":
            n1, n2 = r1["net"][k], r2["net"][k]
        else:
            g1 = allocate(d, r1["order"]) if d > 0 else np.zeros(18, int)
            g2 = allocate(-d, r1["order"]) if d < 0 else np.zeros(18, int)
            n1, n2 = r1["y"] - g1, r2["y"] - g2
        return int((n1 < n2).sum() - (n2 < n1).sum())

    res = {k: defaultdict(lambda: defaultdict(list)) for k in schemes}
    fav = {k: [0, 0, 0] for k in schemes}  # stronger player W/H/L in match play
    favs = {k: [0, 0, 0] for k in schemes}  # stronger player W/T/L in net stroke play
    gapbins = {k: defaultdict(lambda: [0, 0, 0]) for k in schemes}
    nseeds = 0
    for rs in by_seed.values():
        if len(rs) < 2:
            continue
        nseeds += 1
        for k in schemes:
            tot = [r["net"][k].sum() for r in rs]
            stb = [stableford(r, k) for r in rs]
            for r, p1, p2, t, sb in zip(
                rs, pct(tot), pct(stb, False), tot, stb, strict=True
            ):
                d = res[k][r["player"]]
                d["stroke_pct"].append(p1)
                d["stb_pct"].append(p2)
                d["net_vs_par"].append(t - r["par"].sum())
                d["stb"].append(sb)
            for r1, r2 in itertools.combinations(rs, 2):
                if strength[r1["player"]] > strength[r2["player"]]:
                    r1, r2 = r2, r1  # r1 is the stronger player
                mres = match(r1, r2, k)
                i = 0 if mres > 0 else 1 if mres == 0 else 2
                fav[k][i] += 1
                res[k][r1["player"]]["whl"].append(i)
                res[k][r2["player"]]["whl"].append(2 - i)
                res[k][r1["player"]]["mp"].append(1 - i / 2)
                res[k][r2["player"]]["mp"].append(i / 2)
                dn = r1["net"][k].sum() - r2["net"][k].sum()
                j = 0 if dn < 0 else 1 if dn == 0 else 2
                favs[k][j] += 1
                gap = strength[r2["player"]] - strength[r1["player"]]
                gapbins[k]["<8" if gap < 8 else "8-16" if gap < 16 else "16+"][i] += 1
            # skins: lowest unique net on a hole
            if len(rs) >= 3 and k != "exact":
                netm = np.array([r["net"][k] for r in rs])
                for h in range(18):
                    lo = netm[:, h].min()
                    w = np.where(netm[:, h] == lo)[0]
                    for i, r in enumerate(rs):
                        res[k][r["player"]]["skins"].append(
                            1.0 if len(w) == 1 and w[0] == i else 0.0
                        )
                        res[k][r["player"]]["skins_exp"].append(1.0 / len(rs))

    print(f"\n== B. formats over {nseeds} seeds with >=2 eligible players")
    print(
        "stronger player's record, all pairs   (match play W-H-L | net stroke play W-T-L)"
    )
    for k in schemes:
        w, h, lost = fav[k]
        w2, t2, l2 = favs[k]
        print(
            f"  {k:6} match {w:3}-{h:3}-{lost:3}  ({(w + h / 2) / (w + h + lost):.0%})   "
            f"stroke {w2:3}-{t2:3}-{l2:3}  ({(w2 + t2 / 2) / (w2 + t2 + l2):.0%})"
        )
    print("stronger player's match-play score by skill gap (strokes/18):")
    for k in schemes:
        print(
            f"  {k:6}"
            + "  ".join(
                f"{b}: {(v[0] + v[1] / 2) / sum(v):.0%} (n={sum(v)})"
                for b, v in sorted(gapbins[k].items())
            )
        )

    order_p = sorted(res["gross"], key=lambda p: strength[p])
    for metric, title in (
        ("stroke_pct", "net stroke play finishing percentile (0.5 = fair)"),
        ("stb_pct", "net Stableford finishing percentile"),
        ("mp", "net match play points per match (0.5 = fair)"),
        ("stb", "mean Stableford points (36 = played to handicap)"),
        ("net_vs_par", "mean net score vs par"),
        ("skins", "skins won per hole / fair share"),
    ):
        print(f"\n{title}")
        print(
            f"  {'player':26}{'skill':>6}{'n':>4}" + "".join(f"{k:>8}" for k in schemes)
        )
        for p in order_p:
            line = (
                f"  {p:26}{strength[p]:>+6.1f}{len(res['gross'][p]['stroke_pct']):>4}"
            )
            for k in schemes:
                v = res[k][p][metric]
                if metric == "skins":
                    e = res[k][p]["skins_exp"]
                    line += f"{(np.sum(v) / np.sum(e) if e else float('nan')):>8.2f}"
                else:
                    line += f"{np.mean(v) if v else float('nan'):>8.2f}"
            print(line)
        if metric in ("stroke_pct", "stb_pct", "mp"):
            line = f"  {'corr with skill (rounds)':36}"
            for k in schemes:
                xs = [strength[p] for p in order_p for _ in res[k][p][metric]]
                ys = [v for p in order_p for v in res[k][p][metric]]
                line += f"{np.corrcoef(xs, ys)[0, 1]:>+8.2f}"
            print(line)

    print("\n== C. spread of net result (sd of net-vs-par, 'day' scheme) by player")
    for p in order_p:
        v = res["day"][p]["net_vs_par"]
        s = res["day"][p]["stb"]
        if len(v) >= 5:
            print(
                f"  {p:26}{strength[p]:>+6.1f}  n={len(v):3}  sd net {np.std(v, ddof=1):4.1f}   sd stableford {np.std(s, ddof=1):4.1f}"
            )

    print(
        "\n== D. how fast a new player's rating settles (interaction model, hole effects known)"
    )
    b_all = 1 + gamma * (a_all - abar_all)
    final = s_all * 18
    errs = defaultdict(list)
    for i in range(n_players):
        rr = list(dict.fromkeys(rid[pidx == i]))
        if len(rr) < 12:
            continue
        for kk in (1, 2, 3, 5, 8):
            m = np.isin(rid, rr[:kk])
            est = (
                (b_all[m] * (y[m] - a_all[m])).sum()
                / ((b_all[m] ** 2).sum() + LAM["skill"])
                * 18
            )
            raw = (b_all[m] * (y[m] - a_all[m])).sum() / (b_all[m] ** 2).sum() * 18
            errs[kk].append((est - final[i], raw - final[i]))
    for kk, v in errs.items():
        v = np.array(v)
        print(
            f"  after {kk} rounds: rmse vs final  shrunk {np.sqrt((v[:, 0] ** 2).mean()):.1f}  unshrunk {np.sqrt((v[:, 1] ** 2).mean()):.1f}  (players {len(v)}; shrunk bias {v[:, 0].mean():+.1f})"
        )

    print("\n== E. sandbagging: effect of one thrown round (+15 strokes) on the rating")
    for i, p in enumerate(players):
        m = pidx == i
        nr = m.sum() / 18
        if nr < 3:
            continue
        den = (b_all[m] ** 2).sum() + LAM["skill"]
        # 15 extra strokes spread over 18 holes of average slope
        print(
            f"  {p:26} rounds {nr:4.0f}   rating moves {15 * 18 / (den + 18):+.2f} strokes/18"
        )

    print(
        "\n== F. mean (actual - predicted) round total by player: all-history vs recency"
    )
    for p in order_p:
        rs = [r for r in elig if r["player"] == p]
        print(
            f"  {p:26} n={len(rs):3}"
            + "".join(
                f"  {m} {np.mean([r['y'].sum() - r[f'p_{m}'].sum() for r in rs]):+5.1f}"
                for m in ("int", "hl10", "last8", "b8")
            )
        )

    print("\n== G. match play W-H-L by player and scheme")
    for p in order_p:
        print(
            f"  {p:22}"
            + "  ".join(
                f"{k} {'-'.join(str(res[k][p]['whl'].count(i)) for i in range(3))}"
                for k in schemes
                if k != "exact"
            )
        )

    print("\n== H. season sim: 28 dailies, score = sum of best N net Stableford days")
    rng = np.random.default_rng(1)
    ndays = {
        p: len({w[:10] for w, q in zip(when, player, strict=True) if q == p})
        for p in players
    }
    span = 53
    for k in ("last8", "l8@90", "l8@80"):
        pool = {
            p: np.array([stableford(r, k) for r in elig if r["player"] == p])
            for p in order_p
        }
        pool = {p: v for p, v in pool.items() if len(v) >= 5}
        ps = list(pool)
        print(
            f" scheme {k}: mean/sd daily points: "
            + ", ".join(f"{p[:8]} {pool[p].mean():.1f}/{pool[p].std():.1f}" for p in ps)
        )
        for label, prob in (
            ("actual play rates", {p: min(0.95, ndays[p] / span) for p in ps}),
            ("everyone 60%", dict.fromkeys(ps, 0.6)),
        ):
            print(
                f"  {label}: " + ", ".join(f"{p[:8]} {prob[p] * 28:.0f}d" for p in ps)
            )
            for best_n in (3, 6, 10, 28):
                wins = np.zeros(len(ps))
                rank = np.zeros(len(ps))
                trials = 4000
                for _ in range(trials):
                    sc = []
                    for p in ps:
                        m = rng.binomial(28, prob[p])
                        d = np.sort(rng.choice(pool[p], m))[::-1][:best_n]
                        sc.append(d.sum() + rng.random() * 1e-3)
                    sc = np.array(sc)
                    wins[sc.argmax()] += 1
                    rank += (-sc).argsort().argsort() + 1
                print(
                    f"    best {best_n:2}: win% "
                    + " ".join(
                        f"{p[:8]} {100 * w / trials:4.0f}"
                        for p, w in zip(ps, wins, strict=True)
                    )
                    + "   avg rank "
                    + " ".join(f"{x / trials:.1f}" for x in rank)
                )

    print(
        "\n== I. season sim: daily points = share of that day's field beaten (net Stableford), sum of best N"
    )
    for k in ("last8", "l8@90"):
        pool = {
            p: np.array([stableford(r, k) for r in elig if r["player"] == p])
            for p in order_p
        }
        pool = {p: v for p, v in pool.items() if len(v) >= 5}
        ps = list(pool)
        for label, prob in (
            ("actual play rates", {p: min(0.95, ndays[p] / span) for p in ps}),
            ("everyone 60%", dict.fromkeys(ps, 0.6)),
        ):
            print(f" {k}, {label}")
            for best_n in (3, 6, 10, 28):
                wins = np.zeros(len(ps))
                rank = np.zeros(len(ps))
                trials = 3000
                for _ in range(trials):
                    pts = [[] for _ in ps]
                    for _d in range(28):
                        here = [i for i, p in enumerate(ps) if rng.random() < prob[p]]
                        if len(here) < 2:
                            continue
                        v = np.array([rng.choice(pool[ps[i]]) for i in here])
                        for i, x in zip(here, v, strict=True):
                            pts[i].append(
                                ((v < x).sum() + 0.5 * ((v == x).sum() - 1))
                                / (len(here) - 1)
                            )
                    sc = (
                        np.array([sum(sorted(q, reverse=True)[:best_n]) for q in pts])
                        + rng.random(len(ps)) * 1e-3
                    )
                    wins[sc.argmax()] += 1
                    rank += (-sc).argsort().argsort() + 1
                print(
                    f"    best {best_n:2}: win% "
                    + " ".join(
                        f"{p[:8]} {100 * w / trials:4.0f}"
                        for p, w in zip(ps, wins, strict=True)
                    )
                    + "   avg rank "
                    + " ".join(f"{x / trials:.1f}" for x in rank)
                )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Backtest handicapped formats on a site database (spike)."
    )
    parser.add_argument("db", help="a randomizer site database (golf_site.db)")
    parser.add_argument(
        "--min-holes",
        type=int,
        default=54,
        help="prior holes a player needs for a round to count (default 54)",
    )
    args = parser.parse_args(argv)
    run(args.db, args.min_holes)


if __name__ == "__main__":
    main()
