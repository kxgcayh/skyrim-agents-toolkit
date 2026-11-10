# Knowledgebase: Vanilla reference

Part of the Skyrim modding knowledgebase; index: `KNOWLEDGEBASE.md`. Covers vanilla combat/crafting formulas, FormIDs and bug catalogue.

## Vanilla Game Mechanics & Reference (baseline that gameplay mods edit)

Purpose: when **sorting a modlist** or judging whether two gameplay mods conflict, an agent needs
the vanilla baseline those mods retune — the combat/crafting math, the records that get overridden,
and the bugs that make a mod a "fix" (which must load after what it patches). This is the vanilla
game data, not tooling. Sourced from **UESP** (`en.uesp.net`), the same primary source the rest of
this file uses; the fandom wiki `elderscrolls.fandom.com` 403s automated fetches and is not used.

Conventions that apply throughout:
- **FormIDs are written as 6-digit local IDs under the `00` (Skyrim.esm) prefix**, the way UESP/CK
  write them. The leading master byte is load-order dependent — see *Vanilla Record Reference* for
  how to read it and why the same local ID under a different prefix is a different master.
- Exact IDs must be confirmed in xEdit at edit time; this section names which records collide, not
  an exhaustive dump.
- **VR is untested for all of this** (inherited, flat-Skyrim-verified only) — consistent with the
  fork note at the top.
- Older related entries: *Useful Vanilla MGEFs / Reference FormIDs* (in the VR Papyrus findings
  above) and *Reused vanilla records can carry gating Conditions*.

### Combat & Defense Formulas

**Weapon damage**

```
displayed damage = Round[ (base damage + smithing increase)
                          * (1 + skill/200)
                          * (1 + perk effects)
                          * (1 + item effects)
                          * (1 + potion effect)
                          * (1 + Seeker of Might bonus) ]
```
- Skill: each point of One-handed / Two-handed / Archery = +0.5% damage for the player, **+2% for
  NPCs** (NPCs scale ~4x faster off skill).
- Perk effects = `0.2 * Armsman/Barbarian/Overdraw rank` (rank 5 = `+1.0`, i.e. x2). Multiplicative
  with skill and smithing, so all three multiply together.
- Blessing of Auriel adds into `item effects`; Blessing of Boethiah adds into `potion effect`.
- Smithing increase must be the unrounded value before the Round step.
- Attack speed: `attacks per second = speed / 0.867` (base one-hand attack = 13/15 s).
  Representative speeds: dagger 1.3 (1.50 APS), sword 1.0 (1.154), war axe 0.9, mace 0.8 (0.923);
  greatsword 0.7, battleaxe 0.7, warhammer 0.6.
- Dual-wield off-hand attacks take 50% longer, so dual-wield is ~+33% DPS, not +100%. The off-hand
  weapon's speed governs the whole dual power attack.

Power attack damage (both hands summed):

```
damage = SUM_hands[ displayed * (1 + PAB) * (1 + PAP) * (1 + DPAP) * DPAM ]
PAB = 1 if power attacking            (=> x2 base)
PAP = 0.25 with Savage Strike / Devastating Blow
DPAP = 0.5 with Dual Savagery
DPAM = 1.5 (right) / 3 (left) on a dual power attack, else 1
```

| Attack | Damage | Stagger | Stamina |
|---|---|---|---|
| Single power attack | x2 | x1 | x1 |
| Dual-wield power (3 hits) | x1.5/hit | x1 | x0.5/hit |
| Bash | x0.5 | x0.5 | x1 |
| Power bash | x1.5 | x1.5 | x1 |
| Unarmed power | x2 | x0.5 | x1 |

- Power attack stamina = `(40 + weapon weight * 2) * attack cost multiplier * (1 - perk effect)`;
  Fighting Stance = -25%. Only 1 Stamina is required to power attack (stamina does not scale damage).
- Representative base damage: Iron Sword 9, Steel Sword 10, Daedric Sword 16, Dragonbone Sword 19;
  Iron Dagger 2, Daedric Dagger 6; Iron Greatsword 16, Dragonbone Greatsword 27; Iron Warhammer 24,
  Daedric Warhammer 31, Dragonbone Warhammer 33. Silver weapons: +20 flat vs undead/werewolves
  (not scaled by skill, but scaled by perks/enchantments).
- Difficulty multipliers (multiplied onto everything): Novice NPC x2 / player x0.5; Apprentice
  x1.5 / x0.75; Adept x1 / x1; Expert x0.75 / x1.5; Master x0.5 / x2; Legendary x0.25 / x3. Applies
  to followers and summons too.
- NPC-only `Extra Damage` perks multiply NPC damage independent of skill: x1.12, 1.5, 2, 2.5, 3,
  3.5, 4, 4.5, 5, 6 (2H column usually ~1 lower). Enemy-overhaul mods frequently edit these perk
  records.

*Source: https://en.uesp.net/wiki/Skyrim:Weapons , https://en.uesp.net/wiki/Skyrim:Damage ,
https://en.uesp.net/wiki/Skyrim:One-handed*

**Critical hits**

- Crit extra damage = typically `floor(base damage * 0.5)`, stored per-weapon in the weapon record;
  it **bypasses armor entirely**.
- Crit damage is NOT modified by tempering, weapon skill, Armsman/Barbarian/Overdraw, Fortify skill
  effects, sneak attacks, power attacks, ammo type, or draw power. It scales only with base damage —
  so perks like Bladesman are near-worthless on smithed high-base weapons (~3% expected gain at top
  tier).
- Deep Wounds / Bladesman / Critical Shot: rank 1 = 10% chance, rank 2 = 15% chance and
  `floor(base*0.5)*1.25`, rank 3 = 20% chance and `floor(base*0.5)*1.5`.
- Critical Charge / Great Critical Charge (sprinting power attack) = double crit, 100% chance =
  `2 * floor(base * 0.5)`; stacks on top of the x2 power attack. With Bladesman/Deep Wounds taken,
  the double crit only fires 10/15/20% of the time instead (net lower average sprinting-PA damage).
- Sneak attacks and crits are computed separately and stack.

*Source: https://en.uesp.net/wiki/Skyrim:Damage*

**Armor rating and damage reduction**

```
item rating  = CEILING[ (base rating + item quality) * (1 + 0.4 * (skill + skill effect)/100) ]
                * (1 + Custom Fit / Well Fitted) * (1 + Matching Set) * (1 + Juggernaut / Agile Defender)
shield rating = same but WITHOUT the armor-perk term
displayed rating = SUM(item ratings) + shield rating + armor effects (flesh spells, Lord Stone, ...)
DR% = displayed rating * 0.12 + 3.00 * (number of armor pieces worn, incl. shield)
```
- Each armor point = 0.12% reduction. Hidden bonus = **+25 per piece worn** (4 pieces + shield =
  +125 total), not shown in the UI; the `+3.00 * pieces` term is that hidden bonus as a percentage
  (25 * 0.12 = 3). Clothing/robes get no hidden bonus.
- **Hard cap: 80% physical DR** (x5 effective health). Total rating needed = 667 (= 567 displayed +
  100 hidden for 4 pieces; = 542 displayed + 125 hidden with a shield). The famous **567 displayed**
  (no shield) / **542 displayed** (with shield) cap values.
- Armor reduces **physical damage only**; magic is unaffected.
- Durability scales as `100 / (100 - DR%)` — hyperbolic, so late points of rating are worth more
  until the cap.
- NPC armor formula uses skill coefficient **1.5 instead of 0.4**, and 1.5625 instead of 1.25 for
  the unison perk.
- Smithing: Legendary quality adds +10 per piece, +20 for chest (total +50 for a matched set). With
  100 skill/perks, any tempered heavy set + shield caps; any tempered light set from Elven up +
  shield caps.
- `Dragonhide` = 80% flat physical ignore (armor-independent). Mage Armor perk multiplies flesh
  spells x2 / x2.5 / x3 **only if no ArmorLight/ArmorHeavy keyword item is worn** (shields don't
  count against it); Mage Armor boosts are "armor effects", not "skill effects" — they enter after
  the CEILING term.

*Source: https://en.uesp.net/wiki/Skyrim:Armor , https://en.uesp.net/wiki/Skyrim:Alteration*

**Armor penetration**

Effective rating = `rating * (1 - penetration)`; i.e. to still hit 80% DR you need
`total rating = 667 / (1 - penetration)`.

| Source | Penetration |
|---|---|
| Bone Breaker (mace, 1h) rank 1/2/3 | 25% / 50% / 75% |
| Skullcrusher (warhammer, 2h) rank 1/2/3 | 25% / 50% / 75% |
| Enhanced Crossbow (Dawnguard) | 50% of armor ignored |

- UESP's exact stated figures: vs 75% penetration you need **2,668 total rating**
  (`667 / (1-0.75)`) = **2,268 displayed** (`567 / (1-0.75)`).
- INFERRED (same arithmetic, UESP does not print these): vs 50% (crossbows) → 1,334 total /
  **1,234 displayed with 4 pieces** (the commonly quoted 1234) / 1,209 with shield; vs 25% → 889
  total / 789 displayed. The often-quoted "~860" figure does **not** appear on the UESP Armor page —
  treat it as UNSOURCED/community; UESP's only printed penetration-adjusted numbers are 2,668 and
  2,268.
- Penetration is multiplicative against rating, so it counters the hidden +25/piece too.
  Bone Breaker/Skullcrusher do nothing vs unarmored targets (dragons, animals, Dwemer constructs have
  0 armor rating). Critical hits ignore armor outright (above) — a separate layer from penetration.

*Source: https://en.uesp.net/wiki/Skyrim:Armor , https://en.uesp.net/wiki/Skyrim:One-handed*

**Blocking**

```
Blocked% = (base term) * (1 + Shield Wall perk) * (1 + sum of 4 Fortify Block enchants)
           * (1 + Fortify Block potion) * (fBlockPowerAttackMult if power attack)
shield base term = 45 + 0.2 * BASE (untempered) shield armor rating * (1 + BlockSkill * 1.5 / 100)
weapon base term = 30 + 0.2 * ENEMY weapon base damage * (1 + BlockSkill * 1.5 / 100)
fBlockPowerAttackMult = 0.66
```
- **Block cap 85%**; stacks multiplicatively with armor's 80% → up to **97% total physical
  mitigation**.
- Shield Wall actual values are 10/20/30/40/50% per rank (in-game text is wrong for ranks 1,2,4,5;
  USSEP corrects it).
- Weapon blocking vs creatures/unarmed enemies is flat (enemy weapon base damage = 0): 30% base,
  45% with 5/5 Shield Wall — Block skill does nothing in that matchup. Only the *enemy's* weapon
  base damage matters, not yours (warhammers are "easier to block" than daggers).
- Only base shield armor rating counts for the block formula (tempering still counts for the armor
  formula). Any shield with base rating ≥ 23.33 hits 85% vs normal attacks at 100 skill + 5/5
  Shield Wall. Power attacks need an extra ~52% Fortify Block (from 4 enchants/potions) to still
  reach 85%, because of the x0.66.
- **Elemental Protection** (Block tree): blocking with a shield reduces incoming fire/frost/shock
  **health** damage by 50%, from any direction; stacks with other spell resistances; does not reduce
  magicka/frost-stamina drain.
- Bashing: `weapon bash = base damage * 0.5 * [0.1 + (BlockSkill/100) * (0.5-0.1)] * 3 (power bash)
  * 5 (Deadly Bash)`; `shield bash = base armor rating * 0.5 * [0.1 + (BlockSkill/100) *
  (0.25-0.1)] * 3 * 5`. Enemy variants use 0.25/0.05 caps (lower). Stamina: block ~small, bash 35,
  power bash 55. Fortify Block does NOT increase bash damage.
- Block hitbox = 35° cone (`fCombatHitConeAngle = 35`).
- Bugs worth knowing when patch state matters: vanilla Deflect Arrows forces 85% block vs everything
  (fixed by Official Patch 1.5); NPC `fCombatBlockTimeMax` ≈ 10,000 s (fixed by USSEP 4.3.4 → 16 s).
- Block skill XP scales with damage actually mitigated; shield block = 2x weapon-block XP, shield
  bash = 5x weapon-bash XP.

*Source: https://en.uesp.net/wiki/Skyrim:Block*

**Magic / elemental resistance stacking**

- `Magic Resistance` reduces offensive spell damage by the displayed %; **stacks additively across
  sources but hard-capped at 85%** (for the player; NPCs/followers with 100% are truly immune).
- Sources: Alteration perk Magic Resistance 10/20/30% (ranks at 30/50/70 skill), plus Resist Magic
  enchantments/potions/racial effects — all funnel into the same 85% cap.
- Elemental resists (Resist Fire / Frost / Shock) are each **capped at 85% separately** and are
  applied **multiplicatively after** Resist Magic: UESP's worked example — 100-pt fire spell with
  Resist Magic 85% → 15 pts, then Resist Fire 85% → 2.25 pts = **97.75% total**. So magic resist and
  elemental resist are two distinct layers, not one pool.
- **Spell Absorption is rolled before Magic Resistance** and is a chance to nullify the whole spell
  and refund its magicka (Atronach Stone/perk paths to 100% absorption). Absorption, Resistance and
  Absorb Magicka do not stack as one mechanic — absorption just wins first when it procs.
- Weakness to Magic (alchemy only, no disenchantable enchantment) amplifies damage from magical and
  elemental attacks; weakness-from-poison is not re-amplified by an existing weakness on the target,
  but potion-side-effect and enchantment sources can amplify themselves and each other; Weakness to
  Poison amplifies Weakness to Magic.
- **MOD SORT: any mod that raises or rewrites the 85% caps, reorders resistance application, or edits
  the Magic Resistance perk (00053128-2a) conflicts with every other mod touching those —
  load-order-last wins. Elemental-resist enchantment overhauls and enemy "immune to X" overhauls
  fight the same records.**

*Source: https://en.uesp.net/wiki/Skyrim:Magic_Overview , https://en.uesp.net/wiki/Skyrim:Resist_Fire ,
https://en.uesp.net/wiki/Skyrim:Weakness_to_Magic , https://en.uesp.net/wiki/Skyrim:Alteration*

**Spell cost**

```
Cost = base cost * skill multiplier * perk multiplier * equipment multiplier * dual cast multiplier
skill multiplier = 1 - (skill / 400)^0.65        (= ~0.5939 at skill 100, i.e. -41%)
equipment multiplier = 1 - (sum of Fortify <school> enchantment reductions)   // 4x25% = 0 cost
dual cast = x2.8 cost for x2.2 effect (vs two single casts: 2.0 cost for 2.0 effect)
```
- Perk multipliers: Novice/Apprentice/Adept/Expert/Master tier perks halve cost (x0.5), stacking
  with the skill term. Dual-cast Destruction = +10% damage for +40% magicka; Healing = +10% heal
  rate for +40% magicka.

*Source: https://en.uesp.net/wiki/Skyrim:Magic_Overview*

**Stagger**

- Stagger chance = base chance x weapon stagger multiplier x attack-type multiplier. Weapon stagger
  values: dagger 0, sword 0.75, war axe 0.85, mace 1.0, greatsword 1.1, battleaxe 1.15, warhammer
  1.25 (Stalhrim non-dagger melee +0.1), bows 0 (Power Shot: 50% chance of 0.25), crossbows 0.75.
- Attack-type multipliers (from the power attack table): normal/power single x1, bash x0.5, power
  bash x1.5, unarmed power x0.5.
- Perk/shout stagger sources: Impact (Destruction dual cast), Power Shot (Archery), Power Bash,
  Force Without Effort (improves overall stagger %), Unrelenting Force word 3 / Cyclone / Staff of
  Hasedoki → ragdoll instead of stagger. Stagger interrupts the current action; ragdoll adds a
  knockdown + recovery delay.
- UNSOURCED: the numeric *base* stagger chance per attack is not stated on these UESP pages; only
  the multipliers above are sourced. The vanilla `stagger` column on weapon records is the
  per-weapon multiplier.
- **MOD SORT: stagger overhauls typically edit the weapon records' stagger values, the Power
  Bash/Impact perks, and/or the base-chance game settings — two stagger mods stacked will
  double-apply or overwrite; last in load order wins.**

*Source: https://en.uesp.net/wiki/Skyrim:Combat , https://en.uesp.net/wiki/Skyrim:One-handed ,
https://en.uesp.net/wiki/Skyrim:Weapons*

**Where these numbers live (combat-specific; perk/MGEF FormIDs: see Vanilla Record Reference)**

- Weapon damage: weapon records (DNAM base damage, stagger, speed), skill/perk records (Armsman,
  Barbarian, Overdraw, Bone Breaker, Skullcrusher), `crExtraDamage*` NPC perks, difficulty
  multipliers. Two damage overhauls editing the same perk record = last plugin wins; a
  global-formula mod (e.g. one that changes `skill/200`) usually stacks multiplicatively with
  record-level mods (different layers), but two record-level mods on the same weapon/perk conflict.
- Armor: ARMR item ratings, the effect magnitude chain (skill coefficient 0.4/1.5, hidden +25/piece,
  0.12%/point, 80% cap), flesh spells + Mage Armor perk, Dragonhide. Smithing-cap mods and
  armor-rating overhauls both edit these; a "raises the armor cap" mod must edit the cap itself,
  conflicting with any other cap mod.
- Block: `fBlockPowerAttackMult` (0.66), `fShieldBaseFactor` (45), `fBlockWeaponBase` (30),
  `fWeaponBash*`/`fShieldBash*`/`fStamina*Bash*` game settings, Shield Wall perk, Deflect Arrows
  bug state (Official Patch 1.5 / USSEP dependent).
- Resistances: 85% magic cap, 85% per-element cap, application order (absorb → magic resist →
  elemental resist). Enchantment overhauls raising resist caps conflict with each other and with any
  mod enforcing vanilla caps.
- Criticals: crit damage is per-weapon record data and armor-bypassing; a mod adding "crit scales
  with X" changes the engine-side crit path and conflicts with weapon-record crit edits.
- General rule: game *settings* (gameSetting records) and *perk records* are single-owner — if two
  gameplay mods touch the same one, the later plugin in load order wins the whole record, not a
  merge; formula mods and record mods stack multiplicatively only when they touch different layers.

### Crafting & Leveling Formulas

Reference for judging whether crafting mods stack, overwrite, or fight. Smithing (cross-checked
against UESP Leveling: `XP = quantity * (25 + 3*value^0.65)`; tempering
`XP = 3.8 * Δvalue^0.5 * Δquality^0.5`) is consistent with the combat section above.

**General skill-XP machinery (all skills):**

```
skill XP to next level  = SkillImproveMult * (currentlevel-1)^1.95 + SkillImproveOffset
skill XP from one use   = SkillUseMult * baseXP + SkillUseOffset
character XP per skillup = new skill level * fXPPerSkillRank (1.0)
```

| Skill | UseMult | ImproveMult | ImproveOffset | baseXP per craft |
|---|---|---|---|---|
| Alchemy | 0.75 | 1.6 | 65 | 1 per gold value created + 1 flat per successful potion |
| Enchanting | 900 | 1 | 170 | 1 per item enchanted (flat); disenchant 1 per 400 gold of enchantment value; recharge 0.05/0.1/0.2/0.4/0.6 (Petty→Grand) |
| Smithing | 1 | 0.25 | 300 | 25 + 3*value^0.65 per item |

- Total XP 15→100: Smithing ~91,601; Enchanting ~278,852; Alchemy ~428,568. Enchanting XP is
  completely independent of item value, enchantment, or soul size — flat per craft; Fortify
  Enchanting potions do NOT increase Enchanting XP. Alchemy XP is dominated by the gold-cost term
  (flat part is +1, vs Smithing's flat +25 — this is why pre-1.5 iron-dagger spam worked for
  Smithing but Alchemy always rewarded high-value potions). XP multipliers (Mage/Thief/Warrior Stone,
  Well Rested, etc.) stack multiplicatively on these.

*Source: https://en.uesp.net/wiki/Skyrim:Leveling , https://en.uesp.net/wiki/Skyrim:Alchemy ,
https://en.uesp.net/wiki/Skyrim:Enchanting*

**Alchemy — magnitude:**

```
magnitude = round(Base_Mag * 4 * (1 + AlchemySkill/200)
                  * (1 + FortifyAlchemy%/100) * (1 + AlchemistPerk%/100)
                  * (1 + PhysicianPerk%/100) * (1 + Benefactor%orPoisoner%/100)
                  * (1 + SeekerOfShadows%/100))
```
- `4` = game setting `fAlchemyIngredientInitMult`; the skill term is
  `1 + (fAlchemySkillFactor-1)*skill/100` with `fAlchemySkillFactor=1.5` (+0.5%/level, +50% at
  100). Only ONE of Benefactor (+25, potions with beneficial effects) / Poisoner (+25, poisons) is
  ever active; Physician (+25) only on Restore Health/Magicka/Stamina. Alchemist perk is
  0/20/40/60/80/100. Duration-scaled effects (Invisibility, Paralysis, Slow, Waterbreathing only)
  apply the same multiplier to `Base_Dur`; all other effects have fixed duration.
- `Base_Mag`/`Base_Dur` come from the EFIT field of the **highest-priority ingredient** (priority =
  effect cost in CK data), not averaged. Non-standard ingredients override: River Betty 2.5x Damage
  Health magnitude, Crimson Nirnroot 3x, Deathbell 1.5x, Jarrin Root 100x mag / 158.5x value,
  Nirnroot 12.6x gold value only.

**Alchemy — gold value (= XP driver):**

```
gold_cost = floor(Base_Cost * max(Magnitude^1.1, 1) * (Duration>0 ? (Duration/10)^1.1 : 1))
```
- Multi-effect potions: cost computed per effect, total = sum. Highest-cost effect decides name and
  potion-vs-poison classification — decided BEFORE perks are applied. Purity perk zeroes
  opposing-sign effects, which *reduces* gold value. Hidden internal magnitudes/durations still feed
  the cost formula (e.g. Cure Disease value rises with "magnitude" that does nothing in-game). Known
  engine bug: many Damage Health ingredients use a 1s duration in the cost calc instead of 0s.

*Source: https://en.uesp.net/wiki/Skyrim:Alchemy , https://en.uesp.net/wiki/Skyrim:Alchemy_Effects*

**Enchanting — apparel magnitude:**

```
vanilla:        net = base * soulMult * skillMult(effective skill) * (1+EnchanterPerk) * (1+specificPerk) * (1+SeekerOfSorcery)
with USKP:      net = base * soulMult * skillMult * (1+FortifyEnchPotion) * (1+EnchanterPerk) * (1+specificPerk) * (1+SeekerOfSorcery)

skillMult = 1 + (skill/100) * (skill/100 - 0.14) / 3.4     // quadratic; +25.29% at skill 100
effective skill (vanilla) = base skill + FortifyEnchanting potion magnitude + Ahzidal's Genius(10) + Haunting Gift(10 each)
```
- Soul multiplier: Grand 1, Greater 2/3, Common 1/3, Lesser 1/6, Petty 1/12. Soul charge capacity:
  3000/2000/1000/500/250. Base magnitude = value at Grand soul, 0 skill, no perks.
- The vanilla/USKP split is real and behavioral: vanilla adds the potion into *skill* (subject to the
  quadratic and the 200 asymptote); USKP applies it as a separate multiplier and stops
  Necromage/Fortify-Restoration from touching enchanting. A USKP-style patch and a gameplay overhaul
  that edits the same Fortify-X enchantment records conflict directly — patch must load after.
- Enchanter perk +20/40/60/80/100%; Fire/Frost/Storm Enchanter and Insightful (skill enchants)/Corpus
  (Health/Magicka/Stamina + regen) each +25%; these ADD together and also stack with Destruction
  Augmented perks on weapons (up to x2.25 for two elements). Stalhrim: Frost/Resist Frost/Chaos +25%.
- Weapon max magnitude uses the same formula (soul size excluded unless it would drop charges below
  1), then x(1+Destruction perk); charges per use
  `= 3 * (baseCost * mag/maxMag)^1.1 * (1 - sqrt(skill/200))`; net uses = soul capacity / charges per
  use. Skill 200 = infinite charges (asymptote); 110 (Ahzidal's Genius) is the vanilla cap; Fortify
  Enchanting is deliberately NOT skill for this reason.
- Caps/ceilings: max natural enchant multiplier ~3.132x (100 skill, all perks, Grand soul);
  ~4.21875x with a Fortify Enchanting potion without exploits. Enchanted-item value = base item
  value + enchantment value (additive) — and a documented bug makes the *monetary value* of player
  enchantments DECREASE as Enchanting skill rises (charges are recalculated at use time, not craft
  time: a weapon enchanted under a huge potion drains fast when later used without it).
- Disenchant: destroys item, teaches effect only (magnitude irrelevant), one-time per effect;
  XP = enchantment gold value/400. Fortify Enchanting potion window is 30s; the item-rename screen
  pauses the timer (standard speedrun micro-optimization).

*Source: https://en.uesp.net/wiki/Skyrim:Enchanting , https://en.uesp.net/wiki/Skyrim:Enchanting_Effects*

**Alchemy <-> Enchanting feedback loop:**

```
Fortify Alchemy gear -> stronger Fortify Enchanting potion -> stronger Fortify Alchemy enchantments -> ...
```
- Amplifiers in the loop: 5 gear slots possible only via the Falmer-helmet+circlet bug (otherwise 4);
  Seeker of Shadows (+10% alchemy) / Seeker of Sorcery (+10% enchants) are mutually exclusive but
  freely swappable at the Sallow Regent Black Book; Ahzidal's Genius +10 Enchanting skill; vampire
  Necromage +25% to all self enchantments/potions (bug; USKP removes it). Fortify Restoration potions
  re-amplify active Fortify Skill potions on re-equip — that is the famous unbounded exploit;
  multiple same-type Fortify Skill potions do NOT stack, but Restoration boosts any of them.
- Community/UESP stated ceilings (page carries verification-needed flags — treat as INFERRED): max
  Fortify Enchanting potion +40% legit vanilla, +61% with falmer+circlet and Necromage; one tester
  reached 122% after ~8 loop rounds without Necromage; USKP world: 44% max potion, 114% with Rare
  Curios ingredients, 127% with Haunting Gift, strongest Fortify Alchemy enchant +68%, +272% total
  across four pieces.
- Loop has diminishing returns because each multiplier is (1+x) applied to a base that itself grew;
  there is no hard engine cap on potion magnitude or enchant magnitude — balance is entirely a data
  decision, which is exactly what crafting overhauls change.

*Source: https://en.uesp.net/wiki/Skyrim:Enchanting ("Maximizing Enchantment Power") ,
https://en.uesp.net/wiki/Skyrim:Leveling (exploit section) ,
https://en.uesp.net/wiki/Skyrim:Alchemy_Effects (stacking rules)*

**MOD-SORTING implications (crafting):**

- Every formula above is data-driven, not code: `fAlchemyIngredientInitMult`, `fAlchemySkillFactor`,
  per-effect MGEF `BaseCost`/`BaseMag`/flags (`PowerAffectsMagnitude`, `NoMagnitude`,
  `NoDuration`), per-ingredient INGR `EFIT` entries, ENCH base magnitudes/costs, and the perk records.
  Two crafting overhauls that edit the same MGEF/INGR/ENCH/perk records do NOT merge — plain record
  conflict, last plugin in load order wins, silently. There is no "stacking" of two magnitude
  retunes.
- The pivot records gameplay mods fight over: the **Fortify Alchemy / Fortify Enchanting / Fortify
  Smithing / Fortify Restoration MGEFs and their enchantment entries** (vanilla has no obtainable
  Fortify Enchanting enchantment — only the potion MGEF; mods adding the enchantment edit
  MGEF+ENCH+keyword sets). A mod that retunes these changes the entire loop's balance point; load
  order between it and USKP-style patches (which altered the vanilla Necromage/Fortify-Restoration
  enchanting interactions) is decisive — patches after overhauls, always.
- Enchantment slot legality is keyword-driven (which body slots accept which effect). Mods that add
  enchantable slots or new Fortify-Skill enchantments edit KYWD+ENCH; conflicts show up as
  "enchantment missing from station" rather than stat fights.
- Ingredient strength multipliers (Giant's Toe 5.9x Fortify Health cost, Salmon Roe, Rare Curios
  doubling ingredients) live on INGR records — an alchemy overhaul overriding INGRs and a mod adding
  new ingredients both touch the same records if they edit the same ingredients; USSEP already
  overrides many INGR/MGEF records, so any overhaul must load after it or inherit its fixes/bugs
  unpredictably.
- XP-rate changes (mods making crafting level slower) edit the Actor Value skill-use/improve
  multipliers and/or game settings — global ActorValue data, so *any* two mods touching them conflict
  even if they target different skills, depending on how they bundle (raw AV edits vs scripts).

*Source: https://en.uesp.net/wiki/Skyrim:Alchemy_Effects ,
https://en.uesp.net/wiki/Skyrim:Enchanting_Effects , https://en.uesp.net/wiki/Skyrim:Leveling
(record-level mapping INFERRED from formula-to-CK-field correspondence)*

Skipped: full per-effect Base_Cost/Base_Mag tables (389-line UESP tables — fetch
`Skyrim:Alchemy_Effects` when exact numbers are needed). Risk: several loop-ceiling numbers (+61%,
122%) sit on UESP pages flagged "verification needed" — treat as community-computed.

### Vanilla Record Reference (FormIDs & EditorIDs)

Recognize which vanilla records a gameplay mod overrides or depends on, and predict who wins.

**How to read a FormID**

- A FormID is **8 hex digits**: the **first 2 digits = master index byte**, the last **6 digits =
  local ID** inside the file that owns the record. Treat it as a *local ID + load-order-dependent
  prefix*, never an absolute address.
- The master byte is the index of the owning master **in the referencing plugin's own master list**
  (for Skyrim.esm records, in the game's load order). `000cb40d` and `010cb40d` are two different
  records — the same local ID under a different prefix means a different master file.
- Conventional prefixes (vanilla SSE/AE order): `00` = Skyrim.esm (never changes), `01` = Update.esm,
  `02` = Dawnguard.esm, `03` = Hearthfires.esm, `04` = Dragonborn.esm. Load any plugin between them
  and the DLC prefixes shift; always read the prefix from the actual load order.
- `ff` = runtime/dynamically allocated (summons, script-created items) — never document, never patch.
- `FE` = light/ESL-flagged plugins (incl. Creation Club): the master byte becomes `FE`, followed by a
  **3-hex-digit load-order slot** (`000`–`FFF`) and a 3-hex local ID (`FE000ABC`). The slot is
  assigned by plugin order (CC content orders alphabetically among itself), so it **varies per
  install** — treat any `FExxxxxx` ID as "per-install, confirm with `help` or xEdit".
- **EditorIDs are stable across load orders; FormID prefixes are not.** When diagnosing which record
  a mod touched, match on EDID (`Enchanter00`, `CraftingSmithingForge`).
- Conflict rule for everything below: records are **overwritten whole; field-by-field merging does
  not exist**. The last plugin in load order that overrides a record wins *all* of it; two mods
  touching the same record need a conflict-resolution patch (forward both changes).
- IDs below are 6-digit local IDs under the `00` Skyrim.esm prefix. Perk IDs cross-checked against
  Skyrim.esm (EDID → FormID); keyword/MGEF IDs likewise.

*Source: https://en.uesp.net/wiki/Skyrim:Form_ID*

**Key gameplay perks (PERK records)**

Most-overridden vanilla perk records. FormID = **rank 1**.

| Perk (EDID) | FormID | Who typically overrides |
|---|---|---|
| SteelSmithing | 000cb40d | USSEP, crafting overhauls (CCO/CCOR), armor-set mods |
| ArcaneBlacksmith | 0005218e | crafting overhauls, magical-item tempering patches |
| DragonArmor | 00052190 | crafting overhauls, DLC-item add-ons |
| Armsman00 (One-handed) | 000babe4 | combat overhauls (Valhalla etc.), perk overhauls |
| Bladesman / BoneBreaker / HackAndSlash | 0005f56f / 0005f592 / 0003fffa | weapon-specialization rebalances, perk overhauls |
| DualFlurry / DualSavagery | 00106256 / 00106258 | combat overhauls, dual-wield fixes |
| SavageStrike / CriticalCharge / FightingStance | 0003af81 / 000cb406 / 00052d50 | combat overhauls |
| Barbarian / Champion'sStance / DevastatingBlow / GreatCriticalCharge | 000babe8 / 00052d51 / 00052d52 / 000cb407 | combat overhauls |
| DeepWounds / Sweep / Warmaster / Skullcrusher | 0003af83 / 0003af9e / 0003afa7 / 0003af84 | combat overhauls, bleed-mod patches |
| ShieldWall / DeflectArrows / ElementalProtection / BlockRunner | 000bccae / 00058f68 / 00058f69 / 00106253 | combat overhauls, shield mods |
| PowerBash / DeadlyBash / DisarmingBash / ShieldCharge / QuickReflexes | 00058f67 / 0005f594 / 00058f66 / 00058f6a / 000d8c33 | combat overhauls, VR mods (timed-block rewrites) |
| Stealth00 / Backstab / DeadlyAim / AssassinsBlade | 000be126 / 00058210 / 001036f0 / 00058211 | stealth overhauls, sneak-damage rebalances |
| MuffledMovement / SilentRoll / ShadowWarrior | 00058213 / 00105f24 / 00058214 | stealth overhauls |
| Overdraw00 / CriticalShot / PowerShot / SteadyHand / Bullseye | 000babed / 00105f1c / 00058f62 / 00103ada / 00058f64 | archery overhauls, combat overhauls |
| AugmentedFlames / AugmentedFrost / AugmentedShock | 000581e7 / 000581ea / 00058200 | magic/damage rebalance mods, perk overhauls |
| IntenseFlames / DeepFreeze / Disintegrate | 000f392e / 000f3933 / 000f3f0e | elemental-balance mods |
| Impact / DestructionDualCasting | 000153d2 / 000153cf | spell-cost/stagger rebalances |
| Novice–Master tier perks (Destruction) | 000f2ca8, 000c44bf, 000c44c0, 000c44c1, 000c44c2 | spell-cost overhauls (analogous rows per school) |
| Regeneration (Restoration) | 000581f8 | heal-rate rebalances, vampire mods, perk overhauls |
| Necromage / Recovery / Respite / WardAbsorb | 000581e4 / 000581f4 / 000581f9 / 00068bcc | magic overhauls, undead/vampire mods |
| Enchanter00 / InsightfulEnchanter / CorpusEnchanter / ExtraEffect | 000bee97 / 00058f7e / 00058f7d / 00058f7f | enchanting overhauls, exploit-fix patches |
| Alchemist00 / Physician / Benefactor / Poisoner / Experimenter / Purity | 000be127 / 00058215 / 00058216 / 00058217 / 00058218 / 0005821d | alchemy overhauls (condition on KYWDs — see keyword cluster) |
| MagicResistance / Atronach / Stability / MageArmor30 | 00053128 / 000581f7 / 000581fc / 000d7999 | magic overhauls, standing-stone mods (Atronach stone shares this perk) |
| Juggernaut00 / WellFitted / Conditioning / MatchingSet(Heavy) / ReflectBlows | 000bcd2a / 00058f6f / 00058f6d / 00107832 / 00105f33 | armor-rating rebalances, perk overhauls |
| AgileDefender00 / CustomFit / MatchingSet(Light) / Unhindered / WindWalker | 000be123 / 00051b1b / 00051b17 / 00051b1c / 00105f22 | armor-rating rebalances, perk overhauls |
| Haggling00 / Merchant / Fence / Investor / MasterTrader | 000be128 / 00058f7a / 00058f79 / 00058f7b / 001090a5 | economy overhauls, merchant mods |
| MysticBinding / OblivionBinding / Summoner / Atromancy / TwinSoulS | 000640b3 / 000d799c / 00105f30 / 000cb419 / 000d5f1c | conjuration rebalances, bound-weapon mods |
| Unbreakable / TreasureHunter / ExtraPockets / Poisoned / PerfectTouch | 00058209 / 00105f26 / 00096590 / 00105f28 / 00058205 | thief-tree overhauls, lockpick mods |

**Rank note (critical for perk overhauls):** every rank of a multi-rank perk is a **separate PERK
record with its own FormID**, EDID = base + skill-level suffix. UESP tables list rank 1 only.
Verified examples: `Armsman00 000babe4`, `Armsman20 00079343`, `Armsman40 00079342`,
`Armsman60 00079344`, `Armsman80 00079345`; `Alchemist00 000be127` → `Alchemist80 000c07cd`
(20/40/60 = 000c07ca/cb/cc); `MageArmor30/50/70 = 000d7999 / 000d799a / 000d799b`; same pattern for
`Overdraw`, `Juggernaut`, `Stealth`, `ShieldWall`, `Barbarian`, `AgileDefender`, `Enchanter`. A mod
that "changes Armsman" but not its 4 higher-rank records silently keeps vanilla values on ranks 2–5 —
search by EDID prefix in xEdit, never by one FormID.

**Load-order consequence:** perk records are whole-record conflicts. A perk overhaul (Ordinator,
Vokrii, similar) overrides the vanilla PERK records it touches and must load **after** USSEP and
after any balance patch that edits the same perk — or, if the balance patch must win, the overhaul's
version of that whole perk record must be forwarded into a patch. A patch ordered *before* the
overhaul silently loses every field. Condition-list edits are the usual casualty.

*Source: https://en.uesp.net/wiki/Skyrim:Smithing , https://en.uesp.net/wiki/Skyrim:One-handed ,
https://en.uesp.net/wiki/Skyrim:Block , https://en.uesp.net/wiki/Skyrim:Sneak ,
https://en.uesp.net/wiki/Skyrim:Archery , https://en.uesp.net/wiki/Skyrim:Destruction ,
https://en.uesp.net/wiki/Skyrim:Restoration , https://en.uesp.net/wiki/Skyrim:Enchanting ,
https://en.uesp.net/wiki/Skyrim:Alchemy , https://en.uesp.net/wiki/Skyrim:Alteration ,
https://en.uesp.net/wiki/Skyrim:Heavy_Armor , https://en.uesp.net/wiki/Skyrim:Light_Armor
(rank records cross-checked against Skyrim.esm)*

**Key magic effects (MGEF records)**

**The single most important fact:** vanilla keeps **three parallel MGEF records per effect** — one
channel for spells/abilities, one prefixed `Alch` for potions/poisons, one prefixed `Ench` for gear
enchantments. Editing one channel changes only that channel. A "potions are too strong" fix belongs
in `Alch*`; a "this enchantment is too strong" fix in `Ench*`; they are different records and do
**not** conflict with each other.

| Effect family | Alchemy channel (potion/poison) | Enchantment channel (gear) | Spell / ability channel |
|---|---|---|---|
| Damage Health | AlchDamageHealth 0003eb42 | (damage-on-contact handled per weapon ENCH) | DamageHealthConcSelf 000f4995 |
| Damage Magicka / Stamina | AlchDamageMagicka 0003a2b6 / AlchDamageStamina 0003a2c6 | EnchMagickaDamageFFContact 0005b44f / stamina-damage variant 0005b450 | — |
| Damage Magicka/Stamina Regen (poisons) | AlchDamageMagickaRate 00073f2b / AlchDamageStaminaRate 00073f2c | AbDamageStaminaRateVisible 0001729d / AbDamageHealRateVisible 0001729b | AbDamageHealRate 000c1e8c, AbDamageStaminaRate 000c1e8d, AbDamageMagickaRate 000a1a45 |
| Restore Health / Magicka / Stamina | AlchRestoreHealth 0003eb15, AlchRestoreStamina 0003eb16, AlchRestoreMagicka 0003eb17 | (heal-on-armor via EnchFortifyHealRate…) | RestoreHealthFFSelf 0001cea6, RestoreMagickaFFSelf 000f4996, RestoreStaminaFFSelf 0002f3ba |
| **Regenerate** (Fortify * Rate) | AlchFortifyHealRate 0003eb06, AlchFortifyMagickaRate 0003eb07, AlchFortifyStaminaRate 0003eb08 | EnchFortifyHealRateConstantSelf 0007a0f8, …MagickaRate 0007a0fd, …StaminaRate 0007a105 | AbFortifyHealRate 00057b49, AbFortifyMagickaRate 0005312b (standing stones, race/ability) |
| **Resist** Fire/Frost/Shock/Magic/Poison/Disease | AlchResistFire 0003eaea, AlchResistFrost 0003eaeb, AlchResistShock 0003eaec, AlchResistMagic 00039e51, AlchResistPoison 00090041 | EnchResistFireConstantSelf 00048c8b, …Frost 00048f45, …Shock 00049295 (EDID typo `ResistShockt`), …Magic 000b7a35, …Disease 00100e60, …Poison 000ff15e | AbResistFire 00024314, AbResistFrost 00024315, AbResistShock 00024318, AbResistMagic 00053124, AbResistPoison 000aa024, AbResistDisease 000e40d3, AbResistDamage 000cab90 |
| **Absorb** Health/Magicka/Stamina | — (no vanilla absorb potions) | EnchAbsorbHealthFFContact 000aa155, …Magicka 000aa156, …Stamina 000aa157 | AbsorbHealthConcAimed 0008d5be, AbsorbMagickaConcAimed 000f1cfe, AbsorbStaminaConcAimed 000f1d01 |
| Elemental damage (Fire/Frost/Shock) | — | EnchFireDamageFFContact 0004605a, EnchFrostDamageFFContact 0004605b, EnchShockDamageFFContact 0004605c | FireDamageFFAimed 00012f03, FrostDamageFFAimed 0001cea2, ShockDamageFFAimed 0001cea8; concentration: 00013ca9 / 00013caa / 00013cab |
| Paralysis | AlchParalysis 00073f30 | EnchParalysisFFContact 000acbb6 | ParalysisFFContact 0006f702 |
| Cure Disease / Poison | AlchCureDisease 000ae722, AlchCurePoison 00109add | — | CureDiseaseEffect 000fbff5 |
| **Fortify skill** block | `AlchFortify*` **0003eb18–0003eb29** (Alchemy 0003eb18, OneHanded 0003eb19, TwoHanded 0003eb1a, Archery 0003eb1b, Block 0003eb1c, Smithing 0003eb1d, HeavyArmor 0003eb1e, LightArmor 0003eb1f, Pickpocket 0003eb20, Lockpicking 0003eb21, Sneak 0003eb22, Barter 0003eb23, Alteration 0003eb24, Conjuration 0003eb25, Destruction 0003eb26, Illusion 0003eb27, Restoration 0003eb28, Enchanting 0003eb29) | `EnchFortify*ConstantSelf` **0007a0f2–0007a106** (Block 0007a0f3, Carry 0007a0f4, Conjuration 0007a0f5, Destruction 0007a0f6, HeavyArmor 0007a0f9, LightArmor 0007a0fb, Lockpicking 0007a0fc, OneHanded 0007a0ff, Pickpocket 0007a100, Restoration 0007a101, Smithing 0007a102, Sneak 0007a103, Speechcraft 0007a104, StaminaRate 0007a105, TwoHanded 0007a106) + Alchemy 0008b65c, Health 000493aa, Magicka 00049504, Stamina 00049507, ArmorRating 00017120 | ability/race forms (e.g. AbFortify*) |

**Who edits which channel, and the load-order consequence:**
- *Alchemy/poison balance mods, ingredient overhauls* → `Alch*` MGEF (magnitude, duration, BaseCost
  drives potion gold value).
- *Enchanting overhauls, item enchant rebalances, Summermyst-style additions* → `Ench*` MGEF and the
  ENCH records that reference them.
- *Combat overhauls, magic overhauls, spell mods* → the spell-channel MGEF (and separately the SPEL
  records — a mod can change a spell without touching its MGEF).
- *Standing stone / race / vampire / werewolf mods* → the `Ab*` (ability) MGEF, e.g. Atronach stone
  and `AbFortifyHealRate`.
- *USSEP* overrides scattered MGEF across all channels.
- Same-channel edits collide: last plugin wins the entire MGEF (magnitude, cost, flags, keyword list
  KWDA). Different channels never collide. Because a single MGEF's KWDA drives alchemy perk logic, a
  mod that rewrites `KWDA` on `Alch*` effects can break Physician/Benefactor/Poisoner even if
  magnitudes look fine — check KWDA in patches.

*Source: https://en.uesp.net/wiki/Skyrim:Damage_Health ,
https://en.uesp.net/wiki/Skyrim:Fortify_One-handed , https://en.uesp.net/wiki/Skyrim:Regenerate_Health ,
https://en.uesp.net/wiki/Skyrim:Resist_Fire , https://en.uesp.net/wiki/Skyrim:Absorb_Health ,
https://en.uesp.net/wiki/Skyrim:Alchemy_Effects , https://en.uesp.net/wiki/Skyrim:Magical_Effects
(channel IDs cross-checked against Skyrim.esm: UESP's `alchid` = MGEF with `Alch` prefix,
`enchid` = MGEF with `Ench` prefix, `id` = spell-channel MGEF)*

**Key keywords (KYWD records)**

No UESP page lists KYWD FormIDs — IDs below verified against Skyrim.esm (EDID → FormID). Keywords are
referenced, not overridden, by most mods: they appear in KWDA lists on items, MGEFs, perks and
conditions.

| Keyword (EDID) | FormID | Who injects / retargets it |
|---|---|---|
| CraftingSmithingForge | 00088105 | crafting overhauls; forge-menu condition on COBJ recipes |
| CraftingSmithingSharpeningWheel | 00088108 | tempering distribution mods |
| CraftingSmithingArmorTable | 000adb78 | tempering distribution mods |
| CraftingSmithingSkyforge | 000f46ce | Skyrim content mods (Skyforge exclusives) |
| CraftingSmelter / CraftingTanningRack / CraftingCookpot | 000a5cce / 0007866a / 000a5cb3 | station-relocation and Hearthfire-style mods |
| WICraftingSmithing / WICraftingSmithingTempering / WICraftingAlchemy / WICraftingEnchanting | 0004f680 / 0004f6fd / 0004f6e6 / 0004f6dd | crafting-menu/requisition mods |
| WeapTypeSword / WarAxe / Dagger / Mace / Bow / Staff | 0001e711 / 0001e712 / 0001e713 / 0001e714 / 0001e715 / 0001e716 | weapon mods (adding a weapon to a skill perk's condition), perk overhauls changing weapon-type conditions |
| WeapTypeGreatsword / Battleaxe / Warhammer / BoundArrow | 0006d931 / 0006d932 / 0006d930 / 0010d501 | as above |
| WeapMaterialWood / Iron / Steel / Dwarven / Elven / Glass / Orcish / Ebony / Daedric | 0001e717 / 0001e718 / 0001e719 / 0001e71a / 0001e71b / 0001e71c / 0001e71d / 0001e71e / 0001e71f | material-rank mods, tempering/leveled-list mods, perk conditions |
| WeapMaterialImperial / Draugr / DraugrHoned / Falmer / FalmerHoned / Silver | 000c5c00 / 000c5c01 / 000c5c02 / 000c5c03 / 000c5c04 / 0010aa1a | as above |
| ArmorHeavy / ArmorLight | 0006bbd2 / 0006bbd3 | **the** armor-type keywords (vanilla has no `ArmorTypeHeavy`); armor mods and perks (Matching Set, Conditioning) match on these |
| ArmorCuirass / Boots / Helmet / Gauntlets / Shield / Clothing / Jewelry | 0006c0ec / 0006c0ed / 0006c0ee / 0006c0ef / 000965b2 / 0006bbe8 / 0006bbe9 | slot-assignment mods, enchant-slot restrictions |
| ArmorMaterial* block **0006bbd4–0006bbe7** (contiguous: Daedric 0006bbd4, Dragonplate 0006bbd5, Dragonscale 0006bbd6, Dwarven 0006bbd7, Ebony 0006bbd8, Elven 0006bbd9, ElvenGilded 0006bbda, Leather 0006bbdb, Glass 0006bbdc, Hide 0006bbdd, Scaled 0006bbde, Studded 0006bbdf, ImperialLight 0006bbe0, ImperialStudded 0006bbe1, ImperialHeavy 0006bbe2, Iron 0006bbe3, IronBanded 0006bbe4, Orcish 0006bbe5, Steel 0006bbe6, SteelPlate 0006bbe7) | 0006bbd4–0006bbe7 | armorsmith mods, per-material perk conditions, craft-recipe gating |
| VendorItemWeapon / VendorItemArmor / VendorItemJewelry / VendorItemArrow | 0008f958 / 0008f959 / 0008f95a / 000917e7 | merchant/loot-list mods |
| MagicDisallowEnchanting | 000c27bd | mods that block/allow disenchanting or enchanting unique items |
| MagicAlchRestoreHealth / MagicAlchRestoreMagicka / MagicAlchHarmful / MagicAlchBeneficial | 00042503 / 00042508 / 00042509 / 000f8a4e | referenced by the Physician/Benefactor/Poisoner perk conditions; alchemy overhauls edit them (UESP's published script lists 00042503 twice for restore-health and restore-stamina — treat the stamina entry as suspect, verify in xEdit) |
| MagicEnchFortifySmithing / MagicAlchFortifySmithing (and siblings) | 00074f6e / 00065a22 | effect-tagging keywords used by perk and enchant conditions |

**Load-order consequence:** a keyword lives inside its owner record's KWDA array. Two mods adding
*different* keywords to the same vanilla item/MGEF still conflict — the later override's entire KWDA
wins, so the earlier mod's keyword silently vanishes. Conflicts are common between (a) crafting
overhauls and (b) armor/weapon packs both tagging the same vanilla items, and between merchant mods
using `VendorItem*`. Resolution = a patch that unions both KWDA lists. Keyword records themselves
(the KYWD) are rarely overridden; it is their *presence on other records* that is contested. A mod
that adds a keyword must load before any patch that forwards record overrides containing it,
otherwise the reference dangles.

*Source: no UESP page publishes KYWD FormIDs; IDs verified from Skyrim.esm (EDID → FormID).
Keyword semantics: https://en.uesp.net/wiki/Skyrim:Smithing and MGEF KWDA usage documented in
https://en.uesp.net/wiki/Skyrim:Alchemy_Effects*

### Vanilla Bug Catalogue (mod-sorting relevant)

Mod-category key: **[USSEP]** = Unofficial Skyrim Special Edition Patch (record-overriding ESP;
loads right after masters, conventionally first among mods; any later plugin overriding the same
records clobbers its fix unless it forwards it). **[Official]** = fixed in a Bethesda game update
(already present on any current SE/AE install — a mod claiming to fix one is redundant or targets
LE 1.x). **[Fix-mod]** = dedicated community fix mod (ESP and/or SKSE plugin). **[Overhaul]** =
gameplay overhaul that may also incidentally fix or break the bug.

Load-order doctrine (applies throughout): a USSEP-style fix must load before record-touching gameplay
mods only if those mods forward its fixes; in practice USSEP goes first and overhauls/patches that
touch the same records load after it and must be checked with xEdit for the specific records. Two
mods fixing the same bug via the same record = conflict; keep one (usually load the more specific
fix after the general patch).

#### Crafting / Smithing

| Bug | Vanilla symptom | Fixed by | Load-order note |
|---|---|---|---|
| Notched Pickaxe enchantment inert | Text claims +5 Smithing; effect never applies (a flat skill bonus vanilla never grants) | [USSEP] (USKP 2.0.0) | USSEP override on the weapon record; any mod touching Notched Pickaxe loads after USSEP or forwards the fix |
| Ancient Knowledge perk wrong | +25% armor applies to ALL armor (not just Dwarven); +15% applied as tempering boost instead of smithing XP | Altered (not fixed) by [Official] 1.9.26; truly fixed by [USSEP] 1.3.1 | USSEP's version changes Dwarven temper behavior vs official patch — armor-balance mods assuming one behavior conflict; check which the user has |
| Steel Smithing ignores Imperial weapons | Imperial weapons (steel-made) not improvable/forgeable under the perk, though Imperial armor is | [USSEP] 2.0.7 | Record override (keyword on Imperial weapons); conflicts with mods reworking Imperial gear unless patched |
| Ebony 1H war axe/mace value error | Bad base values: unpatched game has Daedric = Ebony (lighter) for 1H axes/maces | [USSEP] corrects the order; [Official] SE 1.6.1130 separately fixed bad values on Glass Mace/Warhammer, Honed Draugr War Axe, Ebony Mace/War Axe, most daggers | Any weapon/leveling mod reworking these records must load after Update.esm and USSEP, forwarding intended values |
| Ebony dagger speed too slow | Wrong (slow) speed stat | [Official] 1.5.24 | Redundant on SE — ignore fix mods claiming this |
| Arcane Blacksmith lost after Legendary reset | Making Smithing Legendary, re-leveling and re-taking Arcane Blacksmith can permanently break tempering of enchanted items | Unfixed (no fix cited on UESP) | Gameplay note; temper-fix mods are [Fix-mod]/[Overhaul], verify individually |
| Mannequin duplication | Taking armor back from a mannequin without leaving the cell duplicates it; mannequins also "walk" | Duplication: [USSEP] 1.2.4; walking: [Official] SE 1.6.629 (MannequinRace immobile) | Mannequin-placement mods (player homes) edit mannequin refs — load after USSEP; residual dupe in CC Saints & Seducers gear |
| Double head-slot gear | Falmer Helmet or Ancient Shrouded Cowl lets you equip a second headpiece; Gauldur Amulet a second necklace | Circlet/Cowl: [USSEP] 1.2; Gauldur: [Official] 1.8 | Record fixes; USSEP's Falmer Helm fix is widely forwarded/undone by exploit-retaining mods — an intentional conflict, user choice |
| Matching Set / Custom Fit fail on certain pieces | Set perks not applied with some armor pieces | [Official] 1.9.26 | Armor mods must set correct armor keywords; keyword errors reintroduce the bug inside the mod's own gear (author responsibility, not load order) |
| Weightless-stack armor exploit | Equipping one piece from a stack makes the whole stack weightless under Conditioning-like perks | Unfixed | Engine behavior; relevant to carry-weight overhauls |

*Source: https://en.uesp.net/wiki/Skyrim:Smithing , https://en.uesp.net/wiki/Skyrim:Glitches ,
https://en.uesp.net/wiki/Skyrim:Patch , https://en.uesp.net/wiki/Skyrim:Special_Edition_Patch*

#### Enchanting / Alchemy

| Bug | Vanilla symptom | Fixed by | Load-order note |
|---|---|---|---|
| Fortify Restoration loop | Fortify Restoration potions buff Fortify Alchemy gear retroactively → exponential crafting; game-breaking enchantments | [USSEP] 1.3.0 (also recomputes max Fortify Enchanting: 44% base, 114% with Rare Curios; disables Necromage/Fortify Restoration boost to enchanting) | Fundamental balance divergence: overhauls built on USSEP assume the loop is dead; two ecosystems, not load-order-solvable |
| Necromage-vampire self-boost | Player flagged undead: all self-targeted spells/perks/potions/enchantments +25% magnitude / +50% duration | [USSEP] 1.2.3 | Vampire overhauls (Sacrosanct et al.) deliberately keep/reshape this — they load after USSEP and re-implement it; a "Necromage fix" mod conflicts with them |
| Recovery perk magnitude frozen wrong | Both Recovery ranks permanently scaled by any Fortify Restoration effect active when the perk is taken | [USSEP] 2.1.3 (recent — older USSEP lacks it) | Version-sensitive: late USSEP fixes don't apply retroactively to taken perks without respec |
| Corpus Enchanter miscalculation | Fortify Health/Magicka/Stamina magnitudes miscalculated | [Official] 1.1 | Redundant on SE |
| Fortify Sneak / Lockpick miscalculate | Bonus to current skill miscalculated | [Official] 1.1 | Redundant on SE |
| Enchanted-item value drops as skill rises | Player-enchanted items' gold value decreases with higher Enchanting (charge-consumption compensation) | Unfixed | Affects economy mods' assumptions; no standard fix |
| Bond of Matrimony / Linwe's set disenchantable into dead effects | Effects learned but cannot be applied | [USSEP] 1.0 | Record change; enchanting-progression overhauls may load after and restore/rework |
| Necromancer Robes wrong disenchantment | Yields Fortify Magicka, not Fortify Magicka Regen | Unfixed per UESP | — |
| Stuck at Arcane Enchanter | Exit soft-locks player | [Official] 1.4.26 | Redundant on SE |
| Renamed same-effect weapons collapse to one name | Equipping/unequipping renamed variants renames them all | [Official] 1.2 | Redundant on SE |
| Myrwatch Staff Enchanter 20x XP | Enchanting XP multiplier missing (hidden 95% reduction perk not applied) | [Official] SE 1.6.318 | Redundant on current SE |

*Source: https://en.uesp.net/wiki/Skyrim:Glitches , https://en.uesp.net/wiki/Skyrim:Enchanting ,
https://en.uesp.net/wiki/Skyrim:Restoration , https://en.uesp.net/wiki/Skyrim:Special_Edition_Patch*

#### Magic / Spells / Perks

| Bug | Vanilla symptom | Fixed by | Load-order note |
|---|---|---|---|
| Grand Healing heals enemies' stamina | Healing spells restore stamina to targets that shouldn't get it (undead/daedra/automata) | [USSEP] 2.0.5 | Spell-record overrides; magic overhauls must forward |
| Respite stamina not applied (Grand Healing, Necromantic Healing, Heal Undead) | Wrong actor/fatigue checks | [USSEP] 4.1.5 | Very recent USSEP version — old installs lack it |
| Circle of Protection hazard visual desyncs | Visible effect disperses before spell expires | [USSEP] 2.0.8 | Minor; same doctrine |
| Circle of Protection + Atronach = free magicka | Standing in own CoP with Atronach perk/stone recharges magicka | Unfixed | Relevant to magic-balance mods |
| Blessing of Talos shows 0% | Active-effects display shows 0% instead of 20% | [Official] SE 1.6.1130 | Redundant on current SE |
| Marked For Death stacks with itself | Shout stacks improperly (permanent drain) | [Official] SE 1.6.629 (undocumented) | Redundant on current SE; older fix mods obsolete |
| Twin Souls ignores vampirism | Dead Thrall second-reanimate slot miscounts for vampires | [Official] SE 1.6.629 (undocumented) | Redundant |
| Magic resistance miscalculation | Resistances not calculated after patch 1.2 | [Official] 1.3.7 (LE-era) | Historical — only unpatched LE 1.2; SE never affected |
| Falling damage miscalculated on high difficulty | Excessive/incorrect fall damage at high difficulties | [Official] 1.9.26 | Redundant on SE |
| Ebony Blade perk miscategorization | Improved by wrong-handed perks | [Official] 1.9.26 | Redundant; relevant when evaluating weapon-record mods on LE |
| Deflect Arrows perk miscalculation | Perk doesn't calculate properly | [Official] 1.5.24 | Redundant |
| Dragon Aspect blocks enchanting | "Insufficient charge for enchantment" while shout active | Unfixed | — |

*Source: https://en.uesp.net/wiki/Skyrim:Restoration , https://en.uesp.net/wiki/Skyrim:Patch ,
https://en.uesp.net/wiki/Skyrim:Special_Edition_Patch , https://en.uesp.net/wiki/Skyrim:Enchanting*

#### Combat / Equipment / UI

| Bug | Vanilla symptom | Fixed by | Load-order note |
|---|---|---|---|
| Bow damage calculated incorrectly | Wrong bow damage values | [Official] 1.6.87 | Redundant on SE |
| Limbsplitter rank 3 / Headsman's Axe / Barbarian perk gaps | Battle axes (rank 3) and Headsman's Axe don't get expected perk bonuses | [Official] 1.5.24 / 1.4.15 | Redundant on SE |
| Hotkey unbind for non-dual-wieldable weapons | Daggers/swords/greatswords un-hotkey when >1 in inventory | Unfixed | Engine/UI; hotkey-manager mods are [Fix-mod] SKSE plugins, no load-order position |
| 3–10s weapon-switch delay in combat | Especially bow→spell or bow→dual wield | Unfixed | Engine; commonly mitigated by animation/behavior overhauls ([Overhaul], behavior-level, order vs ESP fixes irrelevant) |
| Arrows/ice spikes stuck in bodies | Projectile meshes never removed | Arrow-in-world cleanup: [Official] 1.5.24; stuck-on-body variant unfixed | — |
| Projectiles stuck in world never cleaned | Floating arrows accumulate | [Official] 1.5.24 | Redundant |
| Kill-cam vs projectile mismatch | Cinematic kill plays but projectile misses/misfires | Partially addressed across [Official] 1.5.24/1.6.87 killcam fixes | Killcam-adjust mods are [Fix-mod] SKSE (INFERRED, not UESP-sourced) |
| Essential NPCs stuck in kneel | Wounded-state essential NPCs never recover | Unfixed by patches | Stagger/behavior mods incidentally help; no load-order implication |
| Craft-station activation dead click | Station click does nothing, third-person blip | Unfixed | — |
| Container menu scroll jump | Inventory selection jumps a line while moving items | Unfixed; no vanilla-UI-preserving fix | Relevant to UI mods (SkyUI replaces the container menu wholesale — different mechanism) |

*Source: https://en.uesp.net/wiki/Skyrim:Glitches , https://en.uesp.net/wiki/Skyrim:Patch*

#### Quests

| Bug | Vanilla symptom | Fixed by | Load-order note |
|---|---|---|---|
| Blood on the Ice trigger failures | Quest fails to start; Viola/Calixto deaths block progression | Progressive fixes in [Official] 1.4.15 and 1.5.24; residual issues persist in community reports | Dedicated quest-fix mods ([Fix-mod]) override the same quest record USSEP also fixes — load the dedicated fix after USSEP or pick one, never assume both apply. INFERRED on residual specifics |
| Quest scripts not shutting down | Orphaned running quest scripts accumulate in save | [Official] 1.9.26 | Save-bloat class — see below; script-cleaner mods are [Fix-mod] tools run on saves, not plugins |
| Oghma Infinium bookshelf/chest reuse | Book reusable via bookshelf placement or container exploit | Container: [Official] 1.3.7; bookshelf: [Official] 1.9.26 | Redundant on SE |
| Generic items permanently flagged quest items | Item stacks become unusable/undroppable/unsellable | Console workaround vanilla; fixed piecemeal by [USSEP] | USSEP fixes instances, not the class — recurrence after USSEP suggests a mod reintroduced a quest-item flag |
| Quest-start precondition breaks (class) | Clearing a location/holding an item before a radiant quest starts breaks it (White Phial, Driftshade, Knifepoint Ridge, Forbidden Legend, etc.) | Mass-fixed by [Official] 1.4.15; SE includes all | Quest-alteration mods (The Choice Is Yours, timing/delay mods) can re-introduce precondition conflicts; they load after USSEP and are prime suspects when a radiant quest won't start |
| Companion/follower state bugs (class) | Followers over-encumbered after rehiring; Companions not equipping better gear; protected companions killable by poison | [Official] 1.9.26 / 1.4.15 | Follower overhauls ([Overhaul]) re-own these records entirely |

*Source: https://en.uesp.net/wiki/Skyrim:Patch , https://en.uesp.net/wiki/Skyrim:Glitches*

#### Engine / Save / Performance / World-state

| Bug | Vanilla symptom | Fixed by | Load-order note |
|---|---|---|---|
| Save bloat from non-shutting-down scripts | Saves grow, hitches, eventual corruption risk | [Official] 1.9.26 (quest scripts); [USSEP] (record/scripted-asset corrections incl. removing buggy scripts) | Overhauls adding scripts shift bloat risk; not order-fixable — diagnosis category |
| Ash piles never clean up | Resurrected-actor ash piles accumulate in cells | [Official] 1.9.26 | Redundant |
| Cured diseases reappear on reload | Diseases "cured" return after load | [Official] 1.9.29 | Redundant |
| Sabre cat / fox / snow fox spawns break spawn points | Spawning at a respawn point permanently breaks it | [USSEP] 2.0.0 | Leveled-list/encounter-zone mods must forward or conflict |
| Harvestable plants revert on reload | Plants reset after 10 days but revert to prior harvested state on cell save/reload | Unfixed | Green Thumb / plant-harvest mods interact; no standard fix |
| Quicksave CTD after long sessions without a proper save | Quicksave crashes; fixed by making a manual save first | Unfixed (engine) | Relevant to auto-save-tuning mods; SE memory fixes are SKSE-plugin territory (SSE Engine Fixes, Scrambled Bugs, Bug Fixes SSE — [Fix-mod] SKSE DLLs, **no load-order position**, version-pinned; UNSOURCED/community) |
| Load-order-of-operations on cell load | Load completes before ground/key elements exist; scenery pops; interactables dead | Unfixed | Crash/hitch diagnosis class, not order-fixable |
| Werewolf-revert / water-shader / dragon-landing / vampiric-grip crashes | Various CTDs | [Official] 1.6.87, 1.7.7, SE 1.2 | All redundant on current SE (1.6.x) |
| Memory/stability baseline | LE 2GB limit; 4GB LAA in [Official] 1.3.10; SE is 64-bit with its own 1.6.x memory fixes | [Official] | Keep SE fully updated; on LE, LAA + SSME/SKSE memory patch were mandatory (UNSOURCED community memory, LAA mechanism page-cited) |
| Mannequin/duplicate-reference instability; duplicate NPCs | Duplicate NPCs after load; crash on dark-brotherhood-sanctuary entry | [Official] 1.8.145, 1.9.26 | Redundant |
| ESL record range (infrastructure, not a bug) | 1.6.1130 doubled ESL range to 4096 records | [Official] | Matters when sorting: an ESL-flagged mod's compatibility with older game versions depends on this; ESPL limits are load-order-capacity-relevant |

*Source: https://en.uesp.net/wiki/Skyrim:Glitches , https://en.uesp.net/wiki/Skyrim:Patch ,
https://en.uesp.net/wiki/Skyrim:Special_Edition_Patch ,
https://en.uesp.net/wiki/Skyrim_Mod:Unofficial_Skyrim_Patch*

**Sorting heuristics distilled**

- **USSEP is the anchor**: loads immediately after masters; every record-override mod after it
  implicitly decides per-record whether USSEP's fix survives (forwarded) or is replaced (overwritten).
  Two mods "fixing" the same record = per-record winner by order, not coexistence.
- **A mod that fixes a bug USSEP also fixes** is a conflict candidate only for the shared records —
  check with xEdit `conflicts` rather than forbidding the mod wholesale.
- **Overhauls are not fix mods** even when they incidentally fix one bug: they own whole record sets;
  they load after USSEP and their fixes are side effects.
- **SKSE-plugin fix mods (SSE Engine Fixes, Scrambled Bugs, Bug Fixes SSE)** never enter the ESP load
  order; compatibility is game-version pinning, not position. (Community knowledge, not UESP-sourced.)
- **[Official]-patch fixes are not a mod category at all on SE/AE**: any mod advertising them either
  targets LE 1.x or pads its description — flag as redundant.
- Version-sensitivity trap: USSEP fixes tagged with recent versions (2.1.3 Recovery, 4.1.5 Respite) are
  absent from old USSEP copies; diagnosing "USSEP installed but bug present" requires checking the
  USSEP version, not just its presence.
