# Map data

[Natural Earth](https://www.naturalearthdata.com/) cultural vectors, version 5.1.1. The 1:50m zips are unmodified. The Japan file is a subset of the 1:10m admin-1 theme.

| File | Theme |
| --- | --- |
| `ne_50m_admin_0_countries.zip` | Admin 0 — countries |
| `ne_50m_admin_1_states_provinces.zip` | Admin 1 — states and provinces, 1:50m |
| `ne_10m_admin_1_japan_prefectures.zip` | Admin 1 — Japan prefectures only, extracted from 1:10m |

The 1:50m files are the unmodified downloads from `https://naciscdn.org/naturalearth/50m/cultural/`. `SHA256SUMS` is the bytes shipped here.

`ne_10m_admin_1_japan_prefectures.zip` is not a separate Natural Earth product. The 1:50m admin-1 theme has China, the United States, and a few other large countries, and it has no Japan. These prefectures are the Japan rows (`adm0_a3` = `JPN`) of Natural Earth 1:10m admin-1 states and provinces, version 5.1.1, with the columns this map reads (`name`, `name_en`, `name_alt`, `postal`, `iso_3166_2`, `type_en`, `adm0_a3`) and the original coordinates. Other countries and unused columns are not included. Source file: `https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip`.

Natural Earth is in the public domain. Tom Patterson, Nathaniel Vaughn Kelso, and the other contributors renounce all financial claim to the maps. No permission is needed to use, modify, or redistribute them. See the [terms of use](https://www.naturalearthdata.com/about/terms-of-use/).

travel-footprint highlights US states, Chinese provinces (including autonomous regions and municipalities), and Japanese prefectures (including Hokkaido, Tokyo, Kyoto, and Osaka). Other subdivisions can be added later without replacing the country file.

If a 1:50m zip is missing, the renderer downloads it from Natural Earth into the cache (`TRAVEL_FOOTPRINT_CACHE`, or `$XDG_CACHE_HOME/travel-footprint`, or `~/.cache/travel-footprint`) and checks the hash above before using it. The Japan extract ships with the repository and is not downloaded.
