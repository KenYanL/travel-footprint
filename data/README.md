# Map data

Unmodified [Natural Earth](https://www.naturalearthdata.com/) 1:50m cultural vectors, version 5.1.1.

| File | Theme |
| --- | --- |
| `ne_50m_admin_0_countries.zip` | Admin 0 — countries |
| `ne_50m_admin_1_states_provinces.zip` | Admin 1 — states and provinces |

Downloaded from `https://naciscdn.org/naturalearth/50m/cultural/`. `SHA256SUMS` is the bytes shipped here.

Natural Earth is in the public domain. Tom Patterson, Nathaniel Vaughn Kelso, and the other contributors renounce all financial claim to the maps. No permission is needed to use, modify, or redistribute them. See the [terms of use](https://www.naturalearthdata.com/about/terms-of-use/).

This version of the admin-1 theme includes the United States (50 states and the District of Columbia) plus several other large countries. travel-footprint highlights US states only. Other subdivisions can be added later without replacing the country file.

If a zip is missing, the renderer downloads it from Natural Earth into the cache (`TRAVEL_FOOTPRINT_CACHE`, or `$XDG_CACHE_HOME/travel-footprint`, or `~/.cache/travel-footprint`) and checks the hash above before using it.
