# Font Licenses

Fonts used for hook text overlays. All 30 fonts are licensed under the
**SIL Open Font License 1.1** (free for commercial use, redistribution, and
modification) and were sourced from Google Fonts. The previous set
(Capo Sfogliato, Gatchina, Super Hockey, Super Kidpop) was removed in
v2.0.138: Capo Sfogliato rendered Latin text as empty boxes, and the other
three had unknown licenses.

Super Starfish was kept from the old set; it is listed on DaFont as
"100% Free" by fsuarez913 and is also distributed under the OFL.

## Fonts (30)

| Font | File | License |
|------|------|---------|
| Anton | `Anton.ttf` | SIL OFL 1.1 |
| Archivo Black | `Archivo Black.ttf` | SIL OFL 1.1 |
| Baloo 2 ExtraBold | `Baloo 2 ExtraBold.ttf` | SIL OFL 1.1 |
| Bangers | `Bangers.ttf` | SIL OFL 1.1 |
| Barlow Condensed Bold | `Barlow Condensed Bold.ttf` | SIL OFL 1.1 |
| Bebas Neue | `Bebas Neue.ttf` | SIL OFL 1.1 |
| Bitter ExtraBold | `Bitter ExtraBold.ttf` | SIL OFL 1.1 |
| Boogaloo | `Boogaloo.ttf` | SIL OFL 1.1 |
| Caveat Bold | `Caveat Bold.ttf` | SIL OFL 1.1 |
| Chewy | `Chewy.ttf` | SIL OFL 1.1 |
| Comfortaa Bold | `Comfortaa Bold.ttf` | SIL OFL 1.1 |
| DM Serif Display | `DM Serif Display.ttf` | SIL OFL 1.1 |
| Fredoka SemiBold | `Fredoka SemiBold.ttf` | SIL OFL 1.1 |
| JetBrains Mono ExtraBold | `JetBrains Mono ExtraBold.ttf` | SIL OFL 1.1 |
| Lato Black | `Lato Black.ttf` | SIL OFL 1.1 |
| Luckiest Guy | `Luckiest Guy.ttf` | SIL OFL 1.1 |
| Merriweather Black | `Merriweather Black.ttf` | SIL OFL 1.1 |
| Montserrat ExtraBold | `Montserrat ExtraBold.ttf` | SIL OFL 1.1 |
| Nunito Black | `Nunito Black.ttf` | SIL OFL 1.1 |
| Open Sans ExtraBold | `Open Sans ExtraBold.ttf` | SIL OFL 1.1 |
| Oswald Bold | `Oswald Bold.ttf` | SIL OFL 1.1 |
| Permanent Marker | `Permanent Marker.ttf` | SIL OFL 1.1 |
| Playfair Display Black | `Playfair Display Black.ttf` | SIL OFL 1.1 |
| Poppins ExtraBold | `Poppins ExtraBold.ttf` | SIL OFL 1.1 |
| Quicksand Bold | `Quicksand Bold.ttf` | SIL OFL 1.1 |
| Roboto Black | `Roboto Black.ttf` | SIL OFL 1.1 |
| Rubik Black | `Rubik Black.ttf` | SIL OFL 1.1 |
| Super Starfish | `Super Starfish.ttf` | 100% Free (DaFont, fsuarez913) / OFL |
| Titan One | `Titan One.ttf` | SIL OFL 1.1 |
| Zilla Slab Bold | `Zilla Slab Bold.ttf` | SIL OFL 1.1 |

## Notes

- Each file is the single-weight static TTF for the family (Latin subset),
  downloaded from the Google Fonts collection. Before shipping, every file
  was verified to render the full Latin charset (A-Z, a-z, 0-9, common
  punctuation) with no missing-glyph boxes.
- Fonts are bundled as Tauri resources (`tauri.conf.json` resources
  `"fonts/*": "fonts/"`) and listed at runtime by the `list_hook_fonts`
  command, which scans the bundled fonts directory.
- Source: https://fonts.google.com/ — license texts at
  https://openfontlicense.org/ (SIL OFL 1.1).
