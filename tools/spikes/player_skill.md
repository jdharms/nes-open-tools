# Player skill model

As of 2026-11-10. Spike code: `player_skill.py`, beside this file.

The model rates each randomizer player in expected strokes per 18 holes, from every hole
score submitted to the site. It adjusts for which holes, pins and wind each player
happened to draw, so players who never shared a seed can still be compared.

Run it against a copy of the site database:

```
uv run python -m tools.spikes.player_skill ~/golf-prod/golf_site.db
```

It takes several minutes, most of it in the EM loop described under
[Fitting it](#fitting-it).

## The problem

A raw scoring average says as much about the seeds a player drew as about the player.
Seeds range from 54-par short courses to 75-par full courses, and from easy layouts to
brutal ones. Each player only plays some of them.

The site records the data needed to correct for that:

- **Seeds**: 18 hole slots, each with a hole id, a terrain hash (the hole after
  transforms such as mirroring and hazard redraws), a pin, wind, par and distance.
- **Rounds**: at most one per player per seed, with strokes and putts for every hole.

This is a well-known problem in sports ratings. Pro golf's "adjusted scoring average",
Massey ratings and two-way fixed-effects regression all solve versions of it. Every
score is one equation tying a player's skill to the difficulty of what they played, and
with enough overlapping equations both can be solved for at once.

## Version 1: the round model

The first version modeled whole rounds, the way real-life ratings model scores against
courses:

```math
\text{strokes}_{p,s} = \mu + \text{skill}_p + \text{difficulty}_s + \varepsilon
```

Here $p$ is the player, $s$ the seed and $\varepsilon$ the round's luck. Each round is
one row of a linear system $X\beta \approx y$, solved by least squares. Three details
make it well posed:

1. **Pin the average.** Adding 5 to every skill and subtracting 5 from every seed
   difficulty predicts the same scores, so one reference has to be fixed. Here the
   average skill is 0, which makes a skill "strokes relative to the field".
2. **The comparison graph must be connected.** Draw players and seeds as nodes and each
   round as an edge. Skills are only comparable within one connected piece. The site's
   data was fully connected.
3. **Shrink thin estimates.** A rating from one round is mostly luck. A small ridge
   penalty pulls estimates with little data toward the average.

It worked, but it threw information away. A seed only one person played says nothing
about that player that can be separated from the seed's difficulty, so those rounds
counted for nothing. On Oct 19 that was 12 of the 40 seeds with any rounds.

The randomizer moves holes between seeds freely, though, so a seed isn't really the unit
of difficulty. A hole is. That led to version 2.

## Version 2: the hole model

The current model has one equation per hole score, and seeds disappear from it entirely:

```math
\text{strokes} = \mu + \beta_4[\text{par}=4] + \beta_5[\text{par}=5] + \beta_d \cdot \text{distance} + \beta_w \cdot \text{wind} + \text{skill}_p + \text{layout}_h + \text{terrain}_t + \text{pin}_{t,k} + \varepsilon
```

| Term | What it captures | Levels (Nov 10) |
| --- | --- | --- |
| $\mu$, par, distance, wind | A baseline for any hole from its par, its length (per 100 yards, centered) and the wind speed | 5 fixed coefficients |
| skill | The player | 14 players |
| layout | The base hole (`hole_id`), beyond what par and distance predict | 144 |
| terrain | The hole after its transforms (`data_hash`), relative to its layout | 502 |
| pin | The pin position on that terrain, relative to the terrain | 891 |
| $\varepsilon$ | Luck on that hole | |

The last three terms are nested: a pin is a refinement of a terrain, which is a
refinement of a layout. Each is pulled toward its parent unless the data says otherwise.
A seed's difficulty is just the sum of its 18 holes, so the model can also predict how
hard a new seed will play before anyone has played it.

Modeling holes changes three things:

- **18 times more observations.** 212 rounds become 3,816 hole scores.
- **Every round counts.** A hole in a seed only one person played usually appears, or
  has a sibling variant, in other seeds that other people played. That pins down its
  difficulty, so the solo round says something about the player. 20 of the 75 seeds with
  rounds have only one.
- **Even unique holes help.** A hole nobody else played still has a baseline from its
  par and distance. Shrinkage splits any surprise between "harder than its par suggests"
  and "the player had a bad hole".

## Fitting it

The fit is penalized least squares, which is the same thing as a linear mixed model with
skill, layout, terrain and pin as random effects.

**The design matrix.** Each hole score is a row of $X$: a 1 for the intercept, par and
distance and wind values, then a single 1 in each of the four groups (the player's
column, the layout's column and so on). $y$ is the strokes column.

**Shrinkage.** Each group $g$ gets a ridge penalty $\lambda_g$ on its coefficients:

```math
\hat\beta = \arg\min_\beta \; \lVert y - X\beta \rVert^2 + \sum_g \lambda_g \lVert \beta_g \rVert^2 \quad\Longrightarrow\quad (X^\top X + \Lambda)\,\hat\beta = X^\top y
```

A level with lots of data (sirhcman's 936 holes) barely moves under the penalty. A level
with little data (one player's single round, a pin seen twice) is pulled toward zero,
meaning toward its parent's value. The par, distance and wind coefficients are not
penalized.

**Choosing the shrinkage from the data.** $\lambda_g = \sigma^2 / \tau_g^2$, where
$\sigma$ is the per-hole luck and $\tau_g$ is how much that group really varies. Neither
is known in advance, so both are estimated by expectation-maximization (EM), the standard
method for mixed models. Start from a guess, then repeat:

1. Solve for $\hat\beta$ with the current $\lambda$.
2. Set $\sigma^2$ to the mean squared residual.
3. For each group, set $\tau_g^2$ as below, where $n_g$ is the number of levels in $g$.
   The trace term adds back the spread that shrinkage hid.
4. Update $\lambda_g = \sigma^2 / \tau_g^2$.

```math
\tau_g^2 = \frac{\lVert \hat\beta_g \rVert^2 + \sigma^2 \, \operatorname{tr}\!\left[(X^\top X + \Lambda)^{-1}\right]_g}{n_g}
```

An earlier attempt picked $\lambda$ by 5-fold cross-validation over a grid. EM replaced
it because it estimates the four penalties jointly and gives each $\tau$ a meaning: the
real spread of that effect, in strokes per hole.

**Centering and error bars.** Skills are reported relative to the mean of the players'
skills, and multiplied by 18 to read as strokes per round. The covariance of
$\hat\beta$ is $\sigma^2 (X^\top X + \Lambda)^{-1}$. The standard error of a centered
skill comes from that covariance after subtracting the mean, $C \, \text{Cov} \, C^\top$
with $C = I - \tfrac{1}{k}$ for $k$ players, so it is the uncertainty relative to the
field.

## Anchoring to par

Par is a better zero than the field average, because the field changes. Between Oct 19
and Nov 10 four players joined, three of them scoring far above the old field average,
and every "vs field" rating moved by several strokes. None of the established players
actually got better that fast.

To anchor to par, the fitted model predicts every hole slot of every live (not
withdrawn) seed, including holes nobody has played, which fall back on their par and
distance baseline. Averaging predicted score minus stated par over those seeds gives the
field-average player's expected score relative to par:

```math
\text{vs par}_p = \text{offset} + 18 \cdot (\text{skill}_p - \overline{\text{skill}})
```

On Nov 10 the 97 live seeds average a par of 67.9, and the offset is +10.4. On Oct 19 it
was +7.5 (52 seeds, mean par 69.7). The offset moved because the field moved; a
player's "vs par" rating should not, except through new data about that player.

Two cautions:

- **Seeds come in different formats.** Live pars range from 54-par short courses to
  75-par full courses. "Vs par on an average live seed" blends them. If strong players
  gain more on hard courses (see [Weaknesses](#weaknesses-and-next-steps)), a per-format
  anchor would read more naturally.
- **The anchor is only as good as the par-and-distance baseline.** Individual layouts
  vary by about ±0.3 strokes per hole around it.

## Current ratings

Among players with more than one round, sirhcman leads at 7.3 strokes under par on an
average live seed, ±0.9. That's from the Nov 10 backup: 212 rounds, 3,816 hole scores,
14 players. Players are listed best first, using their display names.

| Player | Holes | Vs par per 18 | ±1 SE | Raw avg vs par per 18 |
| --- | --- | --- | --- | --- |
| HeWhoHasNoLife | 18 | −15.9 | 4.1 | −8.0 |
| sirhcman | 936 | −7.3 | 0.9 | −7.2 |
| KillerApp23 | 90 | −4.8 | 2.0 | −6.2 |
| concision | 738 | +4.0 | 0.9 | +4.0 |
| Doomtap | 144 | +5.6 | 1.6 | +7.9 |
| Spleebie | 612 | +5.6 | 1.0 | +5.3 |
| Jason (BrevardBilliards) | 54 | +6.8 | 2.5 | +10.3 |
| Algo | 162 | +8.7 | 1.5 | +7.7 |
| spaces | 234 | +12.2 | 1.3 | +13.3 |
| Dewberries | 324 | +12.7 | 1.2 | +12.9 |
| Close2Spectacular | 414 | +13.2 | 1.1 | +13.0 |
| shkoople | 18 | +26.5 | 4.1 | +24.0 |
| Nash | 36 | +36.9 | 3.0 | +37.5 |
| vortexofdoom | 36 | +41.9 | 3.0 | +40.0 |

Where the model and the raw average disagree, it is correcting for the seeds that player
drew. Doomtap and Jason drew easier seeds than average, so their ratings are 2–3.5
strokes better than their raw averages. HeWhoHasNoLife's one seed played hard for its
par, so the model credits them 8 strokes, but on 18 holes that is ±4. Frequent players
have drawn enough seeds for the luck to even out, and model and raw agree within a
stroke.

The standard error is the uncertainty in the rating itself: about a 2-in-3 chance the
true value is within one SE and 95% within two.

## What drives scores

After luck, the player matters most, and which layout gets drawn matters more than how it
is transformed or where the pin is. EM's estimate of each group's spread, $\tau$, is in
strokes per hole (one standard deviation):

| Source | Nov 10 | Oct 19 |
| --- | --- | --- |
| Luck on a given hole (residual $\sigma$) | 1.06 | 1.07 |
| Player skill | 0.90 | 0.63 |
| Layout, beyond par and distance | 0.30 | 0.40 |
| Terrain variant of a layout (mirror, hazard redraw) | 0.26 | 0.18 |
| Pin position | 0.10 | 0.11 |

Wind adds about +0.02 strokes per unit of speed, so +0.2 per hole at the strongest wind
seen (10).

Skill's spread grew because the newer players widened the field. Per round, luck alone
is about $1.06 \times \sqrt{18} \approx 4.5$ strokes, which is why one round says little
about a player.

## Reading the numbers

A rating is an average over many rounds, not a forecast for the next one. The model is
linear in strokes, so the gap between two ratings is the expected gap in strokes on a
seed of average difficulty.

The Oct 19 data checked this against head-to-heads. The model put sirhcman 16.7 strokes
ahead of Spleebie per round. On the 17 seeds both had played, Spleebie averaged 16.9
strokes more.

Three things limit that reading:

- **Single rounds vary a lot.** The per-round difference between those two had a
  standard deviation of 6.7, so a single round could land anywhere from about +3 to +30.
- **The model understates that spread.** Treating holes as independent predicts about
  4.5 strokes of luck per player per round, or 6.4 for a difference. The observed 6.7
  includes bad-day effects the model doesn't capture.
- **The gap depends on difficulty.** On easy seeds the sirhcman–Spleebie gap was 6–8
  strokes; on hard ones, 24–25. The additive model reports one number for every seed, so
  it is right on an average seed and off by several strokes on easy or hard ones.

A rating from one round, like HeWhoHasNoLife's or shkoople's, carries a ±4 error bar
and should not be ranked against ratings built from hundreds of holes.

## Weaknesses and next steps

The biggest known gap is that skill appears to scale with difficulty. Roughly in order
of value:

| Weakness | Effect today | Fix |
| --- | --- | --- |
| Strong players gain more on hard holes | One rating for all seeds; wrong by several strokes on easy or hard ones | Add an interaction, $\text{skill} \times (1 + \gamma \cdot \text{hole difficulty})$, or fit on a log scale; the hole data should pin $\gamma$ down |
| Holes in a round aren't independent | Error bars too narrow; a bad day spreads across 18 holes | Add a per-round "form" term |
| Blowup holes (6.3% of holes are +3 or worse, up to +7) | One disaster swings a thin rating | A robust loss (Huber), or model blowups as a separate probability |
| Skill changes over time | Old rounds count as much as new ones | Weight recent rounds more, or let skill drift slowly |
| Wind is one speed term | Ignores direction relative to the hole and its length | Use headwind/crosswind components scaled by distance |
| Players choose their seeds | Some selection bias (sirhcman plays seeds he created) | Hard to remove; the model already handles it better than raw averages |
| EM converges slowly | The Nov 10 fit hit its 500-iteration cap | A mixed-model library (REML), or faster EM updates |
| Par and distance terms read only together | Distance is centered across all pars | Center distance within each par |

Two uses beyond player ratings:

- **Calibrating hole difficulty.** The fitted layout, terrain and pin effects are
  measured difficulty for every played hole: ground truth for the paused difficulty
  solver (ADR 0012), and the source for real handicap rankings.
- **Long game and putting.** Splitting each score into strokes to reach the green and
  putts allows separate ratings for each. On Oct 19, 76–86% of sirhcman's edge over each
  regular opponent came from reaching the green. Putts alone can't fully separate the
  two, because a good approach leaves a short putt; per-shot "strokes gained" would need
  the ball's distance to the flag on the first putt, which the scorecard QR does not
  carry today.
