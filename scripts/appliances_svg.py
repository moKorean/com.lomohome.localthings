"""A drawn group of appliances, shared by both store-image scripts.

The App Store guidelines reject an app image that is "a single flat shape or icon
on a plain, monochrome or transparent background", and ask for driver images
showing recognisable devices on white. Both therefore need an actual depiction of
appliances rather than the app's mark, and it must be the same depiction in both
places, so it lives here instead of being drawn twice.

Ideally this would be a photograph. This repo cannot ship one it has no licence
for, so the group is drawn to the arrangement a product shot uses: tall units in a
row at the back with clear gaps between them, two small ones in front overlapping
the bottom edge for depth. Composed for the 75x75 driver thumbnail first — six
silhouettes, each still readable when the whole group is 75 pixels wide.

Geometry is on a 1000x1000 grid. Ink spans INK_* below; callers need those to
place the group inside a frame of a different shape.
"""

INK_LEFT, INK_RIGHT = 70, 938
INK_TOP, INK_BOTTOM = 150, 876
INK_WIDTH = INK_RIGHT - INK_LEFT
INK_HEIGHT = INK_BOTTOM - INK_TOP

DEFS = """
    <!-- Brushed steel: a light top, a mid band, and a highlight, which is what reads
         as metal rather than flat grey at small sizes. -->
    <linearGradient id="steel" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0.00" stop-color="#dfe4e9"/>
      <stop offset="0.18" stop-color="#f4f6f8"/>
      <stop offset="0.45" stop-color="#ced5dc"/>
      <stop offset="0.72" stop-color="#eef1f4"/>
      <stop offset="1.00" stop-color="#cdd4db"/>
    </linearGradient>
    <linearGradient id="steelDark" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0.00" stop-color="#c3cbd3"/>
      <stop offset="0.30" stop-color="#e2e7ec"/>
      <stop offset="0.65" stop-color="#bcc4cd"/>
      <stop offset="1.00" stop-color="#d5dce2"/>
    </linearGradient>
    <linearGradient id="glass" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#5b6672"/>
      <stop offset="0.5" stop-color="#39424c"/>
      <stop offset="1" stop-color="#4d5865"/>
    </linearGradient>
    <radialGradient id="drumGlass" cx="0.38" cy="0.32" r="0.75">
      <stop offset="0" stop-color="#8e99a5"/>
      <stop offset="0.55" stop-color="#4a545f"/>
      <stop offset="1" stop-color="#2f3740"/>
    </radialGradient>
    <radialGradient id="floorShadow" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#8d949c" stop-opacity="0.42"/>
      <stop offset="0.7" stop-color="#8d949c" stop-opacity="0.12"/>
      <stop offset="1" stop-color="#8d949c" stop-opacity="0"/>
    </radialGradient>
"""

# Only reads as contact shadow over a light background; on the blue app card it
# would be a grey smudge, so it is kept separate from the group itself.
SHADOW = '<ellipse cx="500" cy="866" rx="416" ry="46" fill="url(#floorShadow)"/>'

GROUP = """
  <g stroke="#aeb7c1" stroke-width="4" stroke-linejoin="round">

    <!-- Back row. Each unit keeps a clear gap from its neighbour: touching bodies
         merge into one blob at thumbnail size, which is the whole risk here. -->

    <!-- Refrigerator, the tallest silhouette and the left anchor. -->
    <rect x="70" y="196" width="190" height="664" rx="16" fill="url(#steel)"/>
    <line x1="165" y1="196" x2="165" y2="628" stroke="#b7bfc9" stroke-width="5"/>
    <line x1="70" y1="628" x2="260" y2="628" stroke="#b7bfc9" stroke-width="5"/>
    <rect x="139" y="270" width="11" height="132" rx="5" fill="#98a1ab" stroke="none"/>
    <rect x="180" y="270" width="11" height="132" rx="5" fill="#98a1ab" stroke="none"/>
    <rect x="112" y="690" width="106" height="11" rx="5" fill="#98a1ab" stroke="none"/>

    <!-- Range with its hood: the canopy meets the body so the two read as one
         appliance rather than a trapezoid floating in space. -->
    <rect x="368" y="150" width="64" height="86" fill="url(#steelDark)"/>
    <path d="M 288 236 L 512 236 L 478 322 L 322 322 Z" fill="url(#steelDark)"/>
    <rect x="288" y="322" width="224" height="538" rx="16" fill="url(#steel)"/>
    <rect x="288" y="322" width="224" height="52" rx="16" fill="#39424c"/>
    <circle cx="330" cy="348" r="14" fill="none" stroke="#7d868f" stroke-width="4"/>
    <circle cx="384" cy="348" r="10" fill="none" stroke="#7d868f" stroke-width="4"/>
    <circle cx="432" cy="348" r="10" fill="none" stroke="#7d868f" stroke-width="4"/>
    <circle cx="480" cy="348" r="14" fill="none" stroke="#7d868f" stroke-width="4"/>
    <rect x="310" y="396" width="180" height="14" rx="7" fill="#98a1ab" stroke="none"/>
    <rect x="310" y="440" width="180" height="382" rx="12" fill="url(#glass)"/>
    <rect x="330" y="462" width="140" height="338" rx="6" fill="#2b333c" stroke="none"/>

    <!-- Front-load washer: the most recognisable shape at any size. -->
    <rect x="562" y="344" width="196" height="516" rx="16" fill="url(#steel)"/>
    <rect x="584" y="372" width="152" height="40" rx="9" fill="url(#steelDark)"/>
    <rect x="596" y="384" width="56" height="16" rx="4" fill="#4d5865" stroke="none"/>
    <circle cx="718" cy="392" r="10" fill="#8b949e" stroke="none"/>
    <circle cx="660" cy="620" r="98" fill="url(#steelDark)"/>
    <circle cx="660" cy="620" r="75" fill="url(#drumGlass)"/>
    <ellipse cx="634" cy="591" rx="27" ry="18" fill="#ffffff" opacity="0.22" stroke="none"/>

    <!-- Tower air conditioner: slim, and the type this app verified first. -->
    <rect x="806" y="252" width="132" height="608" rx="26" fill="url(#steel)"/>
    <circle cx="872" cy="372" r="50" fill="url(#steelDark)"/>
    <circle cx="872" cy="372" r="34" fill="url(#drumGlass)"/>
    <g stroke="#b0b9c2" stroke-width="5">
      <line x1="832" y1="480" x2="912" y2="480"/>
      <line x1="832" y1="516" x2="912" y2="516"/>
      <line x1="832" y1="552" x2="912" y2="552"/>
      <line x1="832" y1="588" x2="912" y2="588"/>
    </g>
    <rect x="846" y="644" width="52" height="16" rx="8" fill="#4d5865" stroke="none"/>

    <!-- Front row: two small appliances standing on the floor closer to the viewer.
         They overlap only the lowest edge behind them, and are offset from every
         edge behind them — sharing an edge welds the two into one shape. -->

    <!-- Induction cooktop, the second verified type, shown as a portable unit. -->
    <rect x="180" y="778" width="212" height="98" rx="14" fill="url(#steelDark)"/>
    <rect x="200" y="798" width="172" height="58" rx="8" fill="#2f3740" stroke="none"/>
    <circle cx="236" cy="827" r="18" fill="none" stroke="#7d868f" stroke-width="4"/>
    <circle cx="292" cy="827" r="12" fill="none" stroke="#7d868f" stroke-width="4"/>
    <circle cx="342" cy="827" r="18" fill="none" stroke="#7d868f" stroke-width="4"/>

    <!-- Microwave. -->
    <rect x="655" y="742" width="230" height="134" rx="14" fill="url(#steel)"/>
    <rect x="675" y="764" width="142" height="92" rx="9" fill="url(#glass)"/>
    <rect x="690" y="779" width="112" height="62" rx="5" fill="#2f3740" stroke="none"/>
    <rect x="830" y="764" width="38" height="92" rx="8" fill="url(#steelDark)"/>
    <circle cx="849" cy="789" r="10" fill="#8b949e" stroke="none"/>
    <rect x="839" y="812" width="20" height="34" rx="5" fill="#98a1ab" stroke="none"/>
  </g>
"""
