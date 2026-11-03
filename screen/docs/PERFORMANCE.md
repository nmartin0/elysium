# Performance baseline

One hardware-rendered comparison captured by upstream (God's Eye View) on 22
August 2026 on an Apple M5 in Chrome 150 at 1440 x 900, device pixel ratio 1.
**It was not measured on this fork.** Since then the fork removed the cockpit,
3D aircraft models, the CRT, night-vision and FLIR looks and several layers, so
only the rows for things that still exist are kept below. It is not a minimum
hardware specification, and the original capture files are not included. Treat
it as a reference for what to re-measure, not as a result for this build.

Method: browser cache disabled, three startup samples, 5 seconds of scripted
motion then 5 seconds at rest per scene, page foregrounded.

## Startup (upstream, median of three)

| App ready | Initial settle | Load event | Motion / rest | Used JS heap |
| ---: | ---: | ---: | ---: | ---: |
| 604.8 ms | 1,855.8 ms | 439.5 ms | 60 / 60 FPS | 105.1 MiB |

## Cold layer activation (upstream)

| Layer | Activation | Source count | Motion / rest | Used JS heap |
| --- | ---: | ---: | --- | ---: |
| Space Missions | 3,581 ms | 26 | 60 / 60 FPS | 131.3 MiB |
| Bikeshare | 2,069 ms | 633 | 60 / 60 FPS | 157.4 MiB |
| Datacenters | 818 ms | 4,362 | 59.6 / 60 FPS | 328.2 MiB |
| Flights | 668 ms | 247 | 60 / 60 FPS | 118.4 MiB |
| Submarine cables | 615 ms | 2,629 | 60 / 60 FPS | 412.0 MiB |

Submarine cables used the most heap, then datacenters.

## Detection labels and visual styles (upstream)

| Scene | Motion / rest |
| --- | ---: |
| Idle globe | 60 / 60 FPS |
| Flights | 60 / 60 FPS |
| Detection at 25% | 39.3 / 41.1 FPS |
| Detection at 50% | 37.4 / 39.8 FPS |
| Detection at 100% | 34.4 / 35.5 FPS |
| Normal | 60 / 60 FPS |
| Anime | 60 / 59.8 FPS |
| Noir | 47 / 56.6 FPS |

Detection scenes processed about 8,170 observations; selected labels rose from
14 at 25% to 56 at 100%. The aircraft rows came from an earlier pass because
the clean rerun received no live aircraft.

## Keyed live sources (upstream)

Captured with the page visible but not focused, so do not compare directly
with the rows above.

| Source | Population | Activation | Motion / rest |
| --- | ---: | --- | ---: |
| NASA FIRMS | 100,430 detections in 3,557 cells | 30.0 s | 32.1 / 55.2 FPS |
| AISStream | 12,000 vessels | 6.4 s | 22.1 / 29.8 FPS |

These populations change continuously; record live counts again in any new
capture.

## Rules for a new capture

1. Record the exact GPU renderer and reject software rendering.
2. Use 1440 x 900 at device pixel ratio 1 with the page focused.
3. Measure cache-disabled startup separately from cold layer activation.
4. Repeat startup three times and compare medians.
5. Record live object counts before attributing a difference to the client.
6. Treat a live-source outage as missing coverage, not as low render cost.

Not established: Windows performance, memory capacity, other GPUs or
viewports, and any measurement of this fork.
