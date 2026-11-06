# Lighting the product like the room

## How the light is built (image mode)
1. **Rebuilt room (env mesh)**: MoGe's 3D surface of everything visible, textured with the image itself and set to
   *emit* its own pixels. The product therefore receives the room's real colours and brightness pattern as bounce
   light, and reflects the actual room in glossy or metal parts. This alone often looks right for soft, indirect interiors.
2. **World**: a uniform colour for what's behind the camera (average image colour). Raise `world.strength` if the
   camera-facing side of the product looks too dark compared with nearby objects.
3. **Explicit lights**: only what the image can't provide:
   - Direct sun or a hard key (the image's pixels are display-referred and clipped, so a window's real power is far higher).
   - Light sources that sit outside the frame but visibly shape the shadows.
4. **Calibration**: two quick probe renders measure how much light the support surface gets from (1) the room and
   (2) your lights. With `target_albedo`, one scale factor is applied to all lights so that
   `image brightness = albedo × light`. The proxy surface's bounce colour is also set consistently.

## Reading the image
| What you see | Light to add |
|---|---|
| Crisp shadows with sharp edges, bright patches on the floor/wall | `sun`, `angle_deg` 0.5–2, through the window. Direction from patch → window, or `--sun-from-shadow` |
| Soft shadows that fade toward one side | `area` at the window or soft source, size = window size, `target` = room centre |
| Almost no shadows, overcast / indirect | no key; maybe `world.strength` 1.2–1.5 |
| Warm pools near lamps | `point` (bare bulb) or `area` (shade) at the lamp, 2700–3000 K |
| Downlights / track spots | `spot` above the product, aimed down, 3000–4000 K |
| Arch render with a sun + sky | `sun` + rely on env; renders usually have clean, physically consistent shadows: match their angle closely |

**Shadow softness** is set by the source's size as seen from the product: sun `angle_deg` (0.5 = razor, 3 = soft),
area light `size` and distance. Compare the penumbra width of an existing shadow near the product.

**Direction check**: in the preview, the product's shadow should point the same way as the shadows of objects near
it, and the same way the light patches fall. If the image's shadows fan out (a nearby lamp), use a point light at
the lamp instead of a sun.

## Colour
`analyze_light.py` reports a Kelvin estimate for the ambient light. The env mesh already carries the room's colour,
so set the key's `kelvin` from what the light *is* (daylight, tungsten). Warm interiors: keys 2700–3500 K.
Daylight through windows: 5500–6500 K, with blue-ish fill (already in the env).

## Typical numbers before calibration
Calibration fixes the overall level. These only set ratios between lights:
sun `strength` 3–5, window area `power` 150–400 W per m², lamp point 40–100 W, spot 100–400 W.
