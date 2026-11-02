# travel-footprint

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="demo/travel-map.png" />
  <source media="(prefers-color-scheme: light)" srcset="demo/travel-map-light.png" />
  <img alt="Demo world map of fictional visited countries, US states, and cities" src="demo/travel-map-light.png" />
</picture>

A Pacific-centred world map of countries, US states, and cities, drawn for a profile README.

*Reusable GitHub Action and Python CLI. One dark PNG, one light PNG, from a YAML file you keep in the repo.*

The preview above is fictional. `scripts/make_demo.py` rebuilds it from a fixed random seed: countries spread across every continent, a handful of US states, and city dots inside those shapes. It is not a real itinerary. Disputed territories, and a fixed list of sensitive countries in that script, are left out. The same command also writes `demo/travel-map-christmas.png`.

![Same fictional demo with the Christmas palette](demo/travel-map-christmas.png)

See [CHANGELOG.md](CHANGELOG.md) for the history of this action.

## Use it

Put `travel.yml` in the repository (start from [`travel.example.yml`](travel.example.yml)), then generate the map next to a [contrib-tetris](https://github.com/KenYanL/contrib-tetris) graph and publish both from `dist/`:

```yaml
name: Publish profile graphics

on:
  schedule:
    - cron: "41 7 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: KenYanL/contrib-tetris@v1
        with:
          github_user_name: ${{ github.repository_owner }}
          svg_light_path: dist/tetris-contrib.svg
          svg_dark_path: dist/tetris-contrib-dark.svg
          palette: auto

      - uses: KenYanL/travel-footprint@v1
        with:
          config: travel.yml
          output: dist
          palette: auto

      - name: Publish to the output branch
        uses: crazy-max/ghaction-github-pages@v5
        with:
          target_branch: output
          build_dir: dist
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

The map files land at the root of `output` as `travel-map.png` (dark) and `travel-map-light.png` (light). Embed them with:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/output/travel-map.png" />
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/output/travel-map-light.png" />
  <img alt="Places I have been" src="https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/output/travel-map-light.png" />
</picture>
```

`travel-map.png` is the dark map. The light map is `travel-map-light.png`.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `config` | no | `travel.yml` | YAML file of countries, US states, and cities. |
| `output` | no | `dist` | Directory for the two PNGs. |
| `palette` | no | `default` | `default`, `halloween`, `christmas`, or `auto`. |

`auto` uses the Halloween colors on 31 October (UTC), the Christmas colors on 24, 25, and 26 December (UTC), and the green map every other UTC day. The same rule as contrib-tetris. Omit `palette` to keep the green map on every day, including those holidays.

Invalid values fail the step before any PNG is written. The message names the field and a valid example.

### Outputs

| Output | Description |
| --- | --- |
| `map_dark_path` | Path of `travel-map.png`. |
| `map_light_path` | Path of `travel-map-light.png`. |

The action installs its Python dependencies into a virtualenv on the runner, then runs `travel_footprint.py`. Map data ships inside the action, so the step does not download Natural Earth.

## Config

`travel.yml` is a mapping with three keys. Leave a key out, or use an empty list, when you have nothing to draw for it.

```yaml
countries:
  - IS
  - NZ
  - Chile
us_states:
  - Colorado
  - ME
cities:
  - name: Sample Harbor
    lat: 64.15
    lon: -21.95
```

| Key | What it draws |
| --- | --- |
| `countries` | The whole country in the visited color. ISO 3166-1 alpha-2, alpha-3, or an English name (`NZ`, `NZL`, `New Zealand`). `UK` and `US` are accepted. |
| `us_states` | Only those states, in the visited color. The rest of the United States stays plain land. A name or USPS code (`Wyoming`, `WY`). The District of Columbia is accepted. Other subdivisions are not supported yet. |
| `cities` | A dot at `lat`/`lon` (or `latitude`/`longitude`). Longitude is −180 to 180, latitude −90 to 90. |

Listing `USA` under `countries` fills the whole country, and `us_states` is not drawn on top of it. Listing states alone does not tint Alaska, the other states, or any other unlisted part of the country. A repeated country, an unknown name, a coordinate out of range, or an unknown key fails with a message that quotes the entry. Two-letter codes can stay unquoted: the loader does not read `NO` as a boolean.

## Palettes

The dark map uses the GitHub dark canvas `#0d1117`, land `#30363d`, and a border in the canvas color. The light map uses white, land `#d0d7de`, and the same layout. Default and Halloween city dots on the light map are `#1f2328` so they stay visible. Christmas dots stay `#f2e8cf` on both themes; they sit on the red and green bands.

| Palette | Theme | Visited | Dots |
| --- | --- | --- | --- |
| `default` | dark | `#3fb950`, solid | `#ffffff` |
| `default` | light | `#1a7f37`, solid | `#1f2328` |
| `halloween` | dark | `#c46212`, solid | `#e3d04f` |
| `halloween` | light | `#c46212`, solid | `#1f2328` |
| `christmas` | dark | `#bc4749` with `#6a994e` diagonal stripes | `#f2e8cf` |
| `christmas` | light | `#bc4749` with `#6a994e` diagonal stripes | `#f2e8cf` |

Halloween colors are GitHub Primer `@primer/primitives` 11.10.0 (`--contribution-halloween` on the dark theme). Christmas colors are [Coolors' most popular Christmas palette](https://coolors.co/palettes/popular/christmas) (`386641`, `6a994e`, `a7c957`, `f2e8cf`, `bc4749`). The stripes are 8 pixels wide at the PNG's resolution, half red and half green, clipped to the visited shapes. Default and Halloween stay solid fills.

## How it is drawn

Natural Earth 1:50m, plate carrée, seam at 30°W. Land west of that line is shifted by 360° so the Pacific sits in the middle and the Americas sit on the right. Antarctica is omitted. Countries are simplified slightly, then painted as plain land. A country listed under `countries` is filled in full. A listed US state is filled on its own; the rest of that country is left as land. Christmas then lays pixel-aligned diagonal stripes over those visited shapes. City dots sit on top, with a soft halo. Each PNG is 1200×474.

The coastlines are the unmodified Natural Earth zips in [`data/`](data/README.md), public domain, checked against `data/SHA256SUMS`. If a zip is missing, the CLI downloads it once into `TRAVEL_FOOTPRINT_CACHE`, or `$XDG_CACHE_HOME/travel-footprint`, or `~/.cache/travel-footprint`, and checks the hash before drawing.

## Develop

Python 3.10 or newer.

```bash
python3 -m pip install -r requirements.txt pytest
python3 -m pytest
python3 travel_footprint.py --config travel.example.yml --out dist --palette default
python3 travel_footprint.py --config travel.yml --out dist --palette auto --date 2026-12-25
python3 scripts/make_demo.py
```

`--palette` is the same choice as the action input. `--date` is the UTC day used when the palette is `auto`. Halloween is 31 October. Christmas is 24, 25, and 26 December.

[`.github/workflows/test.yml`](.github/workflows/test.yml) runs the tests on pull requests and on pushes to `main`.

## License

[MIT](LICENSE).

Map data is public domain [Natural Earth](https://www.naturalearthdata.com/about/terms-of-use/), version 5.1.1. See [`data/README.md`](data/README.md).
