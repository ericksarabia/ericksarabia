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
import re
import sys
import textwrap
import unicodedata
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

PIXELS = json.loads((HERE / 'pixels.json').read_text())
CONTENT = json.loads((HERE / 'content.json').read_text())


def palette(name='DARK') -> dict:
    return PIXELS['palette' if name == 'DARK' else 'paletteLight']


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

# Stars per ten thousand square units, back layer first, rather than a count.
# As the log grew the drawing went from 76 units tall to nearly nine hundred
# while the counts stayed where they were, and the sky quietly thinned to a
# third of what it was drawn as — the blinking layer went from one every 2,700
# square units to one every 10,000. A density cannot do that.
STAR_DENSITY = (10.2, 6.8, 3.7)

# Sightings. Log entry zero is a kid seeing something cross the dark before
# dawn, so the sky does it back — rarely enough to be caught rather than
# expected.
#
# "Random" is baked, as everything moving here is: a file that runs no script
# cannot roll for one. What stands in for it is periods sharing no factors, so
# the three never line up and the combined pattern takes tens of minutes to
# come round. They fall leftward, against the way the ship travels, so the two
# are never mistaken for each other.
# One per band down the whole drawing. Three of them, placed at random inside
# the top half, all landed in the top third — and a reader looking at the lower
# half of an image this tall would never have seen one at all. Bands guarantee
# that wherever you are looking, something can cross it.
#
# The periods are primes, so no two ever line up and the whole set only repeats
# after a span nobody will sit through.
SIGHTING_PERIODS = (11, 13, 17, 19, 23, 29, 31, 37, 41, 43,
                    47, 53, 59, 61, 67, 71, 73, 79, 83, 89)
SIGHTING_FLIGHT = 1.1             # how long one is on screen
SIGHTING_REACH = 140              # how far it gets in that time
SIGHTING_DX, SIGHTING_DY = -0.97, 0.24
SIGHTING_TAIL = 12

DRIFT_PASSES = 5
DRIFT_SPEED = 62             # units a second while crossing
DRIFT_OFFSCREEN = 0.15       # share of each pass spent waiting past the right edge
DRIFT_MARGIN = 16            # how far beyond each edge it sits when out of frame
# The heights are one per band so the whole height gets crossed, and the bands
# are shuffled so it does not march predictably down the page.
DRIFT_SEED = 81

# Header lines stack rather than sitting at fixed offsets, because how many an
# entry has varies: a milestone is its company and its role, the closing entry
# is its label and its title, log entry zero is only its label.
HEADER_H = 9                 # advance from one header line to the next
HEADER_SEP = 3               # character widths between the parts of a header
BODY_GAP = 10                # from the last header line to the first of the body

# The collected stack, as labels. The site sets its tags in a 1px box with
# 5px/8px of padding around 11px text; at a five-unit face the same proportions
# come out at two and three.
CHIP_PAD_X, CHIP_PAD_Y = 3, 2
CHIP_GAP_X, CHIP_GAP_Y = 3, 3
CHIP_H = 2 + 2 * CHIP_PAD_Y + 5
# The face is 5 tall and the site leads it at 7. Eight here, one more, because
# the underline needs somewhere to sit: at 7 it lands directly against the top
# of the line below and the two crowd each other. At 8 it has a clear row on
# either side. One unit is also the least this can move — there is no half
# pixel to spend — and it costs 47 units across the log.
LINE_H = 8
UNDERLINE_DY = 6             # a row clear of the glyphs, inside the same line
ENTRY_GAP = 20



def month_index(ym: str) -> int:
    y, m = map(int, ym.split('-'))
    return y * 12 + m - 1


def marked(para: str) -> list:
    """Split a paragraph on its markup into (text, role) runs.

    `[[like this]]` is the place — the company or the school. `{{like this}}`
    is what he was there as. Everything else is prose. The markup exists
    because the two used to sit on a heading line above the story, which read
    as a CV entry; inside the sentence they need to stay distinguishable, and
    the drawing has always done that with tone.
    """
    runs, at = [], 0
    for hit in re.finditer(r'\[\[(.+?)\]\]|\{\{(.+?)\}\}', para):
        if hit.start() > at:
            runs.append((para[at:hit.start()], None))
        runs.append((hit.group(1) or hit.group(2),
                     'place' if hit.group(1) else 'role'))
        at = hit.end()
    if at < len(para):
        runs.append((para[at:], None))
    return runs


def wrap_runs(runs, edu: bool) -> list:
    """Greedy wrap that carries the tones through.

    Returns a list of lines, each a list of (text, class, column). Words never
    straddle a run, because the markup always wraps whole ones, so a word can
    take its tone from the character it starts on.
    """
    # Both take the track's brightest tone, and both are underlined.
    #
    # The role used to take the glow tone, which measures DIMMER against the
    # ground than the prose around it — 128 against 163 in dark — so the thing
    # meant to stand out was sinking instead. There is no tone between the
    # prose and the brightest one in either palette, so the answer is to stop
    # separating place from role by colour: what the reader needs is for both
    # to leave the sentence, not to be told which is which.
    lit = 'eduActive' if edu else 'markerActive'
    tone_of = {None: 'shipCore', 'place': lit, 'role': lit}
    plain, tones = '', []
    for text_run, role in runs:
        plain += text_run
        tones += [tone_of[role]] * len(text_run)

    lines, line, filled = [], [], 0
    for word in re.finditer(r'\S+', plain):
        add = len(word.group()) + (1 if line else 0)
        if line and filled + add > CHARS_PER_LINE:
            lines.append(line)
            line, filled, add = [], 0, len(word.group())
        line.append((word.group(), tones[word.start()], filled + (add - len(word.group()))))
        filled += add
    if line:
        lines.append(line)

    # Neighbouring words in the same tone become one run, so a line of plain
    # prose is drawn once rather than word by word.
    merged = []
    for line in lines:
        out = []
        for text_part, tone, col in line:
            if out and out[-1][1] == tone and out[-1][2] + len(out[-1][0]) + 1 == col:
                out[-1] = (out[-1][0] + ' ' + text_part, tone, out[-1][2])
            else:
                out.append((text_part, tone, col))
        merged.append(out)
    return merged


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

    def rules(pal):
        """One ruleset per palette, keyed the way the groups are classed."""
        out = []
        for key, value in pal.items():
            if isinstance(value, list):
                # trail and stars are ramps: t0..t3 and s0..s2.
                out += [f'.{key[0]}{i}{{fill:{c}}}' for i, c in enumerate(value)]
            else:
                out.append(f'.{key}{{fill:{value}}}')
        return ' '.join(out)

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

    def group(tone, draw, **attrs):
        """Groups carry a palette key as a class, never a colour.

        That is what lets one stylesheet at the top of the file repaint the
        whole drawing for a light browser: the geometry is written once and
        the two palettes are two rulesets over it.
        """
        rects.clear()
        draw()
        if not rects:
            return ''
        extra = ''.join(f' {k}="{v}"' for k, v in attrs.items())
        return f'<g class="{tone}"{extra}>' + ''.join(rects) + '</g>'

    # --- where each entry sits ----------------------------------------------
    #
    # Straight after the one above it. Nothing is positioned by date any more,
    # so nothing can leave a hole.

    stack = list(dict.fromkeys(t for m in stones for t in m['tech']))
    cards = [dict(meta='LOG ENTRY ZERO', name=None, title=None,
                  body=opening(), year=None, edu=False)]
    for i, m in enumerate(stones, 1):
        cards.append(dict(
            # A milestone has no heading at all now. The company and the role
            # are inside the prose, marked up and drawn in their own tones, and
            # a heading above that would only say them twice. `name` and
            # `title` stay in content.json as the record of what the markup is
            # supposed to contain, not as something drawn.
            meta=None, name=None, title=None,
            # The period is not drawn either: the year beside the rail carries
            # when, and `year` also marks which cards are stops on the line,
            # which the rail and the markers both read.
            body=m['story'], year=m['start'].split('-')[0],
            edu=m['kind'] == 'education'))
    # No label above it: "The log continues" is the closing line, and a heading
    # reading END OF THE LINE directly over it said the opposite thing anyway.
    cards.append(dict(meta=None, name=epi['title'], title=None,
                      body=epi['story'] + [epi['stack_label'].upper()],
                      stack=stack, year=None, edu=False))

    cursor = TOP
    for c in cards:
        # Paragraphs each start a fresh line but are not separated by a blank
        # one. The break still reads — a paragraph ends short of the margin and
        # the next begins at it — and thirteen blank lines across the log came
        # to ninety-one units of height doing nothing else.
        #
        # Wrapped by hand rather than with textwrap, because the place and the
        # role are drawn in their own tones inside the prose and a line has to
        # arrive knowing which of its words those are.
        c['lines'] = [line for para in c['body']
                      for line in wrap_runs(marked(para), c['edu'])]
        # A milestone states itself on one line: where, what, and when. Three
        # tones rather than three lines is what keeps them apart — the name
        # brightest, the role in its track's accent, the dates dim.
        where = [(part, tone) for part, tone in (
            (c['name'], 'eduActive' if c['edu'] else 'markerActive'),
            (c['title'], 'eduGlow' if c['edu'] else 'markerGlow'),
        ) if part]
        c['head'] = [seg for seg in ([[(c['meta'], 'text')]] if c['meta'] else [])
                     + ([where] if where else [])]

        if where:
            span = sum(len(t) for t, _ in where) + HEADER_SEP * (len(where) - 1)
            if span > CHARS_PER_LINE:
                raise SystemExit(
                    f'nothing written: the heading {c["name"]!r} needs {span} '
                    f'characters and the column holds {CHARS_PER_LINE}.')

        c['y'] = cursor
        c['body_y'] = c['y'] + (len(c['head']) - 1) * HEADER_H + BODY_GAP
        c['end'] = c['body_y'] + len(c['lines']) * LINE_H

        # Labels flow along the line and wrap, so the block is as tall as the
        # stack needs rather than a number written down here.
        c['chips'] = []
        x, y = TEXT_X, c['end'] + CHIP_GAP_Y
        for label in c.get('stack') or []:
            width = 4 * len(label) + 1 + 2 * CHIP_PAD_X
            if x > TEXT_X and x + width > W - TEXT_RIGHT:
                x, y = TEXT_X, y + CHIP_H + CHIP_GAP_Y
            c['chips'].append((x, y, width, label))
            x += width + CHIP_GAP_X
        if c['chips']:
            c['end'] = y + CHIP_H
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
        group('text', years),
        group('timelineLit', dashes),
        group('marker', lambda: ribbon('work')),
        group('eduMarker', lambda: ribbon('education')),
        group('markerGlow', lambda: markers('work')),
        group('eduGlow', lambda: markers('education')),
        group('timelineLit', connectors),
        group('markerActive', terminus),
    ])

    # --- the log ------------------------------------------------------------

    entries = []
    for c in cards:
        parts = []
        for n, segments in enumerate(c['head']):
            y, x = c['y'] + n * HEADER_H, TEXT_X
            for part, tone in segments:
                parts.append(group(tone, lambda p=part, x=x, y=y: text(p, x, y)))
                x += 4 * (len(part) + HEADER_SEP)
        for n, line in enumerate(c['lines']):
            y = c['body_y'] + n * LINE_H
            for run, tone, col in line:
                x = TEXT_X + col * 4
                parts.append(group(tone, lambda r=run, x=x, y=y: text(r, x, y)))
                if tone != 'shipCore':
                    # A rule under the run, a row below the glyphs. Bold is not
                    # available — smearing a 3x5 face fills its own counters and
                    # needs a wider advance than the column can pay for — so the
                    # underline is what carries the extra weight.
                    parts.append(group(tone, lambda w=len(run) * 4 - 1, x=x, y=y:
                                       px(x, y + UNDERLINE_DY, w, 1)))

        if c['chips']:
            def boxes(c=c):
                for x, y, w, _ in c['chips']:
                    px(x, y, w, 1)                          # top
                    px(x, y + CHIP_H - 1, w, 1)             # bottom
                    px(x, y + 1, 1, CHIP_H - 2)             # left
                    px(x + w - 1, y + 1, 1, CHIP_H - 2)     # right
            parts.append(group('timelineLit', boxes))
            parts.append(group('shipCore', lambda c=c: [
                text(label, x + 1 + CHIP_PAD_X, y + 1 + CHIP_PAD_Y)
                for x, y, _, label in c['chips']]))
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
        tone = min(len(ramp) - 1, (k + 1) // 2)
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
                        f'width="{SHIP_SCALE}" height="{SHIP_SCALE}" class="t{tone}">'
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
    for tone, per_10k in enumerate(STAR_DENSITY):
        # Only the nearest layer twinkles. Blinking the whole sky reads as noise
        # rather than as depth, which is the rule the canvas starfield follows.
        for _ in range(round(per_10k * W * H / 10000)):
            sx, sy = rnd.randrange(W), rnd.randrange(H)
            twinkle = (f'<animate attributeName="opacity" values="1;0;1" '
                       f'dur="{2.2 + rnd.random()*2.4:.2f}s" begin="{rnd.random()*3:.2f}s" '
                       f'repeatCount="indefinite"/>') if tone == 2 else ''
            sky.append(f'<rect x="{sx}" y="{sy}" width="1" height="1" '
                       f'class="s{tone}">{twinkle}</rect>' if twinkle else
                       f'<rect x="{sx}" y="{sy}" width="1" height="1" class="s{tone}"/>')

    # A sighting is a head with a tail walking back up its own flight vector,
    # brightest at the front, in the trail ramp rather than the star ramp.
    #
    # It was built out of the star tones first, and nine of its twelve cells
    # landed on the dimmest of the three, twenty luminance units off the
    # ground — so only the head ever registered and the thing read as a speck.
    # The trail ramp is the one the site keeps for light in motion, and even
    # its faintest step is three times clear of the background. It sits invisible for almost all of its period
    # and then crosses; the opacity keyframes are what make it an event rather
    # than a permanent object, and they also hide the jump back to the start.
    rnd = random.Random(404)
    heads, rules_css = [], []
    bands = len(SIGHTING_PERIODS)
    for i, period in enumerate(SIGHTING_PERIODS):
        x0 = rnd.uniform(W * 0.45, W * 0.98)
        lo, hi = 10 + i * (H - 40) / bands, 10 + (i + 1) * (H - 40) / bands
        y0 = rnd.uniform(lo, hi)
        x1 = x0 + SIGHTING_DX * SIGHTING_REACH
        y1 = y0 + SIGHTING_DY * SIGHTING_REACH
        cells = ''.join(
            f'<rect x="{round(-SIGHTING_DX * t)}" y="{round(-SIGHTING_DY * t)}" '
            f'width="1" height="1" class="t{0 if t == 0 else 1 if t <= 2 else 2 if t <= 6 else 3}"/>'
            for t in range(SIGHTING_TAIL))
        # Where in its own period it crosses, staggered so they do not all
        # arrive in the first seconds of the loop.
        a = rnd.uniform(0.15, 0.75) * 100
        b = a + SIGHTING_FLIGHT / period * 100
        heads.append(f'<g id="f{i}">{cells}</g>')
        rules_css.append(
            f'\n    #f{i} {{ animation: f{i} {period}s linear infinite }}'
            f'\n    @keyframes f{i} {{'
            f' 0%, {a:.3f}% {{ opacity: 0; transform: translate({x0:.0f}px, {y0:.0f}px) }}'
            f' {a + 0.001:.3f}% {{ opacity: 1; transform: translate({x0:.0f}px, {y0:.0f}px) }}'
            f' {b:.3f}% {{ opacity: 1; transform: translate({x1:.0f}px, {y1:.0f}px) }}'
            f' {b + 0.001:.3f}%, 100% {{ opacity: 0; transform: translate({x1:.0f}px, {y1:.0f}px) }}'
            f' }}')
    sighting_svg = ''.join(heads)
    sighting_css = ''.join(rules_css)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W*2}" height="{H*2}" shape-rendering="crispEdges" role="img" aria-label="Erick Sarabia's flight log">
  <title>Erick Sarabia — flight log</title>
  <style>
    /* Two palettes over one drawing. The browser's own setting picks, which is
       the user's rather than GitHub's — someone with the site in dark and the
       system in light gets the light one. That is the only handle an image has:
       an SVG embedded as an image cannot see the page it hangs in.

       Light is not dark inverted. It is the site's own LIGHT palette, where
       dark specks on a light ground would read as dirt rather than stars, so
       the sky is pitched down to grain and the trail's ramp runs the other way
       — ink rather than light. */
    {rules(C)}
    @media (prefers-color-scheme: light) {{ {rules(palette('LIGHT'))} }}

    /* The only thing that travels. Linear, because a crossing that eased in
       and out would look like it was being steered rather than passing. */
    #ship {{ animation: drift {drift_secs}s linear infinite }}{sighting_css}
    @keyframes drift {{ {drift} }}
  </style>
  <defs>{''.join(defs)}</defs>
  <rect width="{W}" height="{H}" class="space"/>
  {''.join(sky)}{sighting_svg}
  <g id="ship" opacity="{SHIP_OPACITY}">{trail}<g class="shipCore">{''.join(edge)}</g><g class="marker">{''.join(core)}</g></g>
  {rail}
  {''.join(entries)}
</svg>
"""

    # An SVG is served as XML and parsed as XML, so a stray angle bracket is
    # not a typo, it is a blank image. CSS comments do not protect one: the
    # markup parser reads <style> content as markup, and an <img> written inside
    # a /* */ comment closes nothing and breaks the file. Checked before it is
    # written, because the failure is silent everywhere downstream.
    # Every class the drawing uses has to resolve, in both palettes. A group
    # given a colour where a palette key belongs matches no rule at all and
    # falls back to black, which on the night ground is simply invisible — that
    # happened, and it reached production, because the check that was here only
    # looked at classes that already looked like names.
    named = set(re.findall(r'class="([^"]+)"', svg))
    for label, block in (('dark', rules(C)), ('light', rules(palette('LIGHT')))):
        defined = set(re.findall(r'\.([^{]+)\{', block))
        if missing := sorted(named - defined):
            raise SystemExit(f'nothing written: {len(missing)} class(es) have no '
                             f'{label} rule and would fall back to black — {missing}')

    try:
        ElementTree.fromstring(svg)
    except ElementTree.ParseError as bad:
        raise SystemExit(f'the SVG this produced is not well-formed XML: {bad}\n'
                         f'nothing was written. An angle bracket inside the '
                         f'<style> block is the usual cause.')

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
