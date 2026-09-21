#!/usr/bin/env python3
"""
Build this profile: the flight log as one animated SVG, and the README it sits
in.

Self-contained on purpose. The drawing began life reading the sprite, the
palette, the bitmap face and the milestones straight out of the starship
-portfolio source, which meant this repo could not be built without that one
checked out beside it. Those four things are now copies, in pixels.json and
content.json, and the two repositories do not know about each other.

The cost of that is the cost of any copy: the words and dates here are a
snapshot of the ones on the site, and nothing reconciles them. Edit
content.json when the site's log changes, or this will quietly go on saying the
old thing.

    python3 build/profile.py          # writes flight.svg and README.md

Why an SVG carries the whole log: a GitHub README may not have <script>,
<style> or style attributes, but it may have <img>, and GitHub serves an SVG
from the repo byte for byte — verified. A browser runs CSS and SMIL inside an
<img>-embedded SVG and only refuses to run scripts. So everything that moves has
to live inside the file, and anything that cannot be computed at view time has
to be computed here and baked in.
"""

import json
import random
import sys
import textwrap
import unicodedata
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

PIXELS = json.loads((HERE / 'pixels.json').read_text())
CONTENT = json.loads((HERE / 'content.json').read_text())


def palette(_name='DARK') -> dict:
    return PIXELS['palette']


def sprite() -> list[str]:
    return PIXELS['sprite']


def glyphs() -> tuple[dict, dict, dict]:
    """The face, plus the two tables that put accents above it."""
    return (PIXELS['glyphs'],
            PIXELS['accentMarks'],
            {ch: tuple(pair) for ch, pair in PIXELS['accented'].items()})


def milestones() -> list[dict]:
    return [dict(m) for m in CONTENT['milestones']]


def opening() -> list[str]:
    """Log entry zero."""
    return CONTENT['opening']


def epilogue() -> dict:
    return CONTENT['epilogue']


# --- fixed text -------------------------------------------------------------

# The face has one dash. An em dash at three pixels wide is the same three
# pixels, so it is not worth a glyph of its own.
SUBSTITUTIONS = {'—': '-', '–': '-', '’': "'"}



# --- geometry ---------------------------------------------------------------
#
# The log runs down the page and the rail runs beside it, but the rail is no
# longer to scale. Each entry takes the height its own text needs and the next
# one starts underneath it, so there is no empty rail anywhere.
#
# That is a real loss and worth naming: on the site the distance between two
# markers IS the time between them, and here it is not — three years at Danone
# and six months at Mantiz take the same room. What carries duration now is the
# period written in each entry, which is words rather than distance. The rail's
# job is reduced to order and track: what came after what, and whether you were
# working or studying.

W = 464
YEAR_RIGHT = 18              # year numbers, right-aligned into their own column
RAIL_X = 26                  # the main line
EDU_RAIL_X = RAIL_X - 3      # education runs on its own rail, as on the canvas
TEXT_X = 40
TEXT_RIGHT = 12
CHARS_PER_LINE = (W - TEXT_X - TEXT_RIGHT + 1) // 4

TOP = 16
DASH_ON, DASH_PERIOD = 3, 8

# The ship crosses the back of the drawing rather than flying the rail. It had
# been flying a rail that no longer stands for a journey, which left it with
# nothing to do; drifting past behind the log is a job it can keep.
#
# One crossing only ever covers one band of a drawing this tall, so it makes
# several: left to right, out of frame, and back in at a different height. The
# reposition happens while it is off canvas, so what is seen is only ever a ship
# going the way its nose points. It never doubles back, which is the one rule
# the flight model has always had.
# Whole number only: every cell becomes a SHIP_SCALE square block, so the
# sprite is enlarged rather than resampled and the pixels stay pixels.
SHIP_SCALE = 2
TRAIL_STEPS = 9              # blots of exhaust behind the engine
# The ship is drawn in shipCore, which is also the colour of the log's body
# text, so at full strength the two read as the same material and the sprite
# looks like a run of glyphs. Half strength drops it below even the dimmest
# tier of text and it reads as what it is: something behind the page.
SHIP_OPACITY = 0.5

DRIFT_PASSES = 5
DRIFT_SPEED = 62             # units a second while crossing
DRIFT_OFFSCREEN = 0.15       # share of each pass spent waiting past the right edge
DRIFT_MARGIN = 16            # how far beyond each edge it sits when out of frame
# The heights are one per band so the whole height gets crossed, and the bands
# are shuffled so it does not march predictably down the page.
DRIFT_SEED = 81

NAME_DY, ROLE_DY = 9, 18     # offsets from an entry's own first line
BODY_DY = 28                 # with a role line above it
BODY_DY_NAMED = 19           # a name but no role, as the closing entry has
BODY_DY_BARE = 9             # neither, as log entry zero has
LINE_H = 7                   # the face is 5 tall; 7 is the site's leading
ENTRY_GAP = 20



def month_index(ym: str) -> int:
    y, m = map(int, ym.split('-'))
    return y * 12 + m - 1


def readme() -> str:
    """The drawing, and nothing else.

    No caption and no link around it: the log is inside the SVG and says all of
    it, and the profile page's own fields already carry where to find him.
    """
    return '''<p align="center">
  <img src="flight.svg" width="928"
       alt="Erick Sarabia's flight log: seventeen years of career as a timeline running down the page, flown in a pixel ship, with every entry beside its own marker">
</p>
'''


def main(out_dir: str) -> None:
    C = palette('DARK')
    SPRITE = sprite()
    GLYPH, MARKS, ACCENTED = glyphs()
    stones = milestones()
    epi = epilogue()
    today = date.today()

    # --- drawing helpers ----------------------------------------------------

    rects: list[str] = []

    def px(x, y, w=1, h=1):
        rects.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/>')

    # Each glyph is defined once and referenced afterwards. Drawn as loose rects
    # the log runs to a megabyte, because a thousand words at five pixels a
    # letter is tens of thousands of rectangles; as <use> it is a fraction of
    # that, and <use> needs no script, so an img-embedded SVG still renders it.
    symbols: dict[str, str] = {}
    defs: list[str] = []

    def symbol(key, grid):
        if key not in symbols:
            body = []
            for r, row in enumerate(grid):
                c = 0
                while c < len(row):
                    if row[c] == '#':
                        run = 1
                        while c + run < len(row) and row[c + run] == '#':
                            run += 1
                        body.append(f'<rect x="{c}" y="{r}" width="{run}" height="1"/>')
                        c += run
                    else:
                        c += 1
            if not body:                      # the space glyph draws nothing
                symbols[key] = ''
            else:
                symbols[key] = f's{len(defs)}'
                defs.append(f'<g id="{symbols[key]}">' + ''.join(body) + '</g>')
        return symbols[key]

    def text(s, x, y):
        """Left-aligned, in the 3x5 face. Mirrors drawText, accents and all."""
        cursor = x
        for ch in unicodedata.normalize('NFC', s.upper()):
            ch = SUBSTITUTIONS.get(ch, ch)
            base, mark = ACCENTED.get(ch, (ch, None))
            if (g := GLYPH.get(base)) is not None:
                if gid := symbol(base, g):
                    rects.append(f'<use href="#{gid}" x="{cursor}" y="{y}"/>')
                if mark:
                    # Above the box, so the letter is not squashed and the
                    # advance width never changes.
                    mk = MARKS[mark]
                    rects.append(f'<use href="#{symbol("~" + mark, mk)}" '
                                 f'x="{cursor}" y="{y - len(mk)}"/>')
            cursor += 4

    def right(s, x_end, y):
        text(s, x_end - (len(s) * 4 - 1), y)

    def group(fill, draw, **attrs):
        rects.clear()
        draw()
        if not rects:
            return ''
        extra = ''.join(f' {k}="{v}"' for k, v in attrs.items())
        return f'<g fill="{fill}"{extra}>' + ''.join(rects) + '</g>'

    # --- where each entry sits ----------------------------------------------
    #
    # Straight after the one above it. Nothing is positioned by date any more,
    # so nothing can leave a hole.

    stack = list(dict.fromkeys(t for m in stones for t in m['tech']))
    cards = [dict(meta='LOG ENTRY ZERO', name=None, role=None, body=opening(),
                  year=None, edu=False)]
    for i, m in enumerate(stones, 1):
        cards.append(dict(
            meta=f'LOG {i:02} / {len(stones):02}   {m["kind"].upper()}',
            name=m['name'],
            role=f'{m["title"]}   {m["period"]}',
            body=m['story'], year=m['start'].split('-')[0],
            edu=m['kind'] == 'education'))
    cards.append(dict(meta='END OF THE LINE', name=epi['title'], role=None,
                      body=epi['story'] + [f'{epi["stack_label"].upper()}   '
                                           + '  '.join(stack)],
                      year=None, edu=False))

    cursor = TOP
    for c in cards:
        lines = []
        for i, para in enumerate(c['body']):
            if i:
                lines.append('')
            lines += textwrap.wrap(para, CHARS_PER_LINE)
        c['lines'] = lines
        c['y'] = cursor
        body_dy = BODY_DY if c['role'] else BODY_DY_NAMED if c['name'] else BODY_DY_BARE
        c['body_y'] = c['y'] + body_dy
        c['end'] = c['body_y'] + len(lines) * LINE_H
        cursor = c['end'] + ENTRY_GAP

    H = cursor - ENTRY_GAP + 10
    rail_top, rail_end = cards[0]['y'] + 2, cards[-1]['y'] + 2

    # --- the rail, drawn twice ----------------------------------------------
    #
    # Everything that changes when the ship passes is emitted once dim and once
    # lit, in the same place. The lit copy is clipped to what the ship has
    # already flown past, so the pass itself is the only thing animated.

    def dashes():
        for wy in range(rail_top, rail_end, DASH_PERIOD):
            px(RAIL_X, wy, 1, min(DASH_ON, rail_end - wy))

    def ribbon(kind):
        # The rail beside an entry, in that entry's own track. It says which of
        # the two you were on and in what order, which is all it can say now.
        for a, b in zip(cards, cards[1:]):
            if a['year'] is None or a['edu'] != (kind == 'education'):
                continue
            x = EDU_RAIL_X if kind == 'education' else RAIL_X
            px(x, a['y'] + 2, 1, b['y'] - a['y'])
            if kind == 'education':
                px(EDU_RAIL_X, b['y'] + 1, RAIL_X - EDU_RAIL_X + 1, 1)

    def markers(kind):
        for c in cards:
            if c['year'] is None or c['edu'] != (kind == 'education'):
                continue
            if kind == 'education':
                px(EDU_RAIL_X - 1, c['y'] + 1, 3, 3)          # square node
            else:
                for dx in (-1, 0, 1):                          # diamond node
                    span = 1 - abs(dx)
                    px(RAIL_X + dx, c['y'] + 2 - span, 1, span * 2 + 1)

    def years():
        for c in cards:
            if c['year']:
                right(c['year'], YEAR_RIGHT, c['y'])

    def connectors():
        # The post from the site's marker: the thing that says which paragraph
        # belongs to which stop.
        for c in cards:
            px(RAIL_X + 2, c['y'] + 2, TEXT_X - RAIL_X - 5, 1)

    def terminus():
        px(RAIL_X - 9, rail_end, 19, 1)

    # One state, not two. The dim-and-lit pair existed so the ship could reveal
    # the rail as it passed; nothing passes along it now, so the rail is simply
    # drawn, in the tones that read best.
    rail = ''.join([
        group(C['text'], years),
        group(C['timelineLit'], dashes),
        group(C['marker'], lambda: ribbon('work')),
        group(C['eduMarker'], lambda: ribbon('education')),
        group(C['markerGlow'], lambda: markers('work')),
        group(C['eduGlow'], lambda: markers('education')),
        group(C['timelineLit'], connectors),
        group(C['markerActive'], terminus),
    ])

    # --- the log ------------------------------------------------------------

    entries = []
    for c in cards:
        parts = [group(C['text'], lambda c=c: text(c['meta'], TEXT_X, c['y']))]
        if c['name']:
            parts.append(group(C['eduActive'] if c['edu'] else C['markerActive'],
                               lambda c=c: text(c['name'], TEXT_X, c['y'] + NAME_DY)))
        if c['role']:
            parts.append(group(C['eduGlow'] if c['edu'] else C['markerGlow'],
                               lambda c=c: text(c['role'], TEXT_X, c['y'] + ROLE_DY)))
        parts.append(group(C['shipCore'], lambda c=c: [
            text(l, TEXT_X, c['body_y'] + n * LINE_H) for n, l in enumerate(c['lines'])]))
        entries.append(''.join(parts))

    # --- ship ---------------------------------------------------------------
    #
    # The sprite as the canvas draws it, nose to the right, because that is the
    # way it travels here. Enlarged by a whole number so every cell becomes a
    # square block and nothing is interpolated.
    #
    # Its tones sit a step below the canvas's own: it passes behind the log and
    # must not outweigh the prose, which is itself drawn in shipCore.

    edge, core = [], []
    for r, row in enumerate(SPRITE):
        c = 0
        while c < len(row):
            if row[c] == '.':
                c += 1
                continue
            run, mark = 1, row[c]
            while c + run < len(row) and row[c + run] == mark:
                run += 1
            (edge if mark == '#' else core).append(
                f'<rect x="{(c - len(row) // 2) * SHIP_SCALE}" '
                f'y="{(r - len(SPRITE) // 2) * SHIP_SCALE}" '
                f'width="{run * SHIP_SCALE}" height="{SHIP_SCALE}"/>')
            c += run

    # The trail is made of the ship's own triangle in miniature, which is what
    # entities/trail.ts does — the same stuff as the ship, on its way out. Three
    # shapes: the freshest cell is the biggest, and they shrink as they fall
    # behind. Mirrored, because the trail points the other way.
    #
    # On the canvas this is a particle system, and a file that runs no script
    # cannot have one, so the plume is placed once and only the flicker moves.
    # Two things that made the first attempt read as debris rather than exhaust:
    # the cells were scattered at random rather than shaped, and they were
    # rounded to whole units instead of to the ship's own grid, so a two-unit
    # block could sit half a pixel off the sprite it came out of. Every cell is
    # a SHIP_SCALE block on a SHIP_SCALE lane now.
    TRAIL_SHAPES = [
        ['#'],
        ['#.', '##', '#.'],
        ['#..', '##.', '###', '##.', '#..'],
    ]
    back = -(len(SPRITE[0]) // 2) * SHIP_SCALE
    ramp = C['trail']
    rnd = random.Random(11)
    plume = []
    for k in range(TRAIL_STEPS):
        x = back - (2 + k * 3) * SHIP_SCALE
        shape = TRAIL_SHAPES[2 if k == 0 else 1 if k <= 2 else 0]
        tone = ramp[min(len(ramp) - 1, (k + 1) // 2)]
        # Straight out of the engine at first, then opening into a cone, with
        # the axis kept alive on alternate steps so it does not part down the
        # middle.
        if k <= 2:
            lanes = [0]
        else:
            spread = ((k - 1) // 2) * SHIP_SCALE
            lanes = [0, -spread, spread] if k % 2 == 0 else [-spread, spread]

        for lane in lanes:
            for r, row in enumerate(shape):
                for c, cell in enumerate(row):
                    if cell != '#':
                        continue
                    plume.append(
                        f'<rect x="{x - c * SHIP_SCALE}" '
                        f'y="{lane + (r - len(shape) // 2) * SHIP_SCALE}" '
                        f'width="{SHIP_SCALE}" height="{SHIP_SCALE}" fill="{tone}">'
                        f'<animate attributeName="opacity" values="1;0.25;1" '
                        f'dur="{0.6 + rnd.random() * 0.8:.2f}s" '
                        f'begin="{rnd.random():.2f}s" repeatCount="indefinite"/></rect>')
    trail = ''.join(plume)


    rnd = random.Random(DRIFT_SEED)
    bands = list(range(DRIFT_PASSES))
    rnd.shuffle(bands)
    heights = []
    for b in bands:
        lo = 24 + b * (H - 48) / DRIFT_PASSES
        hi = 24 + (b + 1) * (H - 48) / DRIFT_PASSES
        heights.append(round(rnd.uniform(lo + 12, hi - 12)))

    entry_x, exit_x = -DRIFT_MARGIN, W + DRIFT_MARGIN
    pass_secs = (exit_x - entry_x) / DRIFT_SPEED / (1 - DRIFT_OFFSCREEN)
    drift_secs = round(pass_secs * DRIFT_PASSES)

    # steps(1) on the keyframe where it leaves: the value is held until the next
    # one and then snaps, so the jump back to the left edge is a cut rather than
    # a slide backwards across the page. Both ends of that cut are off canvas.
    frames = []
    for i, y in enumerate(heights):
        start = i / DRIFT_PASSES * 100
        gone = (i + 1 - DRIFT_OFFSCREEN) / DRIFT_PASSES * 100
        frames.append(f'{start:.3f}% {{ transform: translate({entry_x}px, {y}px) }}')
        frames.append(f'{gone:.3f}% {{ transform: translate({exit_x}px, {y}px); '
                      f'animation-timing-function: steps(1, jump-end) }}')
    frames.append(f'100% {{ transform: translate({entry_x}px, {heights[0]}px) }}')
    drift = ' '.join(frames)

    # --- sky ----------------------------------------------------------------

    rnd = random.Random(1337)
    sky = []
    for tone, count in ((0, 110), (1, 72), (2, 40)):
        for _ in range(count):
            sx, sy = rnd.randrange(W), rnd.randrange(H)
            twinkle = (f'<animate attributeName="opacity" values="1;0;1" '
                       f'dur="{2.2 + rnd.random()*2.4:.2f}s" begin="{rnd.random()*3:.2f}s" '
                       f'repeatCount="indefinite"/>') if tone == 2 else ''
            sky.append(f'<rect x="{sx}" y="{sy}" width="1" height="1" '
                       f'fill="{C["stars"][tone]}">{twinkle}</rect>' if twinkle else
                       f'<rect x="{sx}" y="{sy}" width="1" height="1" fill="{C["stars"][tone]}"/>')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W*2}" height="{H*2}" shape-rendering="crispEdges" role="img" aria-label="Erick Sarabia's flight log">
  <title>Erick Sarabia — flight log</title>
  <style>
    /* The only thing that travels. Linear, because a crossing that eased in
       and out would look like it was being steered rather than passing. */
    #ship {{ animation: drift {drift_secs}s linear infinite }}
    @keyframes drift {{ {drift} }}
  </style>
  <defs>{''.join(defs)}</defs>
  <rect width="{W}" height="{H}" fill="{C['space']}"/>
  {''.join(sky)}
  <g id="ship" opacity="{SHIP_OPACITY}">{trail}<g fill="{C['shipCore']}">{''.join(edge)}</g><g fill="{C['marker']}">{''.join(core)}</g></g>
  {rail}
  {''.join(entries)}
</svg>
"""

    out = Path(out_dir)
    (out / 'flight.svg').write_text(svg)
    md = readme()
    (out / 'README.md').write_text(md)

    print(f'{out}/flight.svg   {len(svg):>7,} bytes  {W}x{H} at {W*2}x{H*2}')
    print(f'{out}/README.md    {len(md):>7,} bytes')
    print(f'  {len(defs)} glyph symbols, {svg.count("<use")} references')
    print(f'  {len(cards)} entries packed, no gaps, {CHARS_PER_LINE} chars per line')
    print(f'  ship: {len(SPRITE[0])*SHIP_SCALE}x{len(SPRITE)*SHIP_SCALE} units, '
          f'trail {trail.count("<rect")} cells over {TRAIL_STEPS} steps, '
          f'{DRIFT_PASSES} crossings over {drift_secs}s')
    print(f'  present = {today:%Y-%m}')



if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT)
