# Hyprland's Lua API (0.56)

the Linux machine runs Hyprland 0.56.1 with the **Lua config parser**, which changes
how `hyprctl` is driven. Most examples online use the older string syntax and
simply fail.

## Dispatch takes a dispatcher object

```bash
hyprctl dispatch workspace e+1        # error: ')' expected near 'e'
hyprctl keyword bind ...              # error: keyword can't work with non-legacy parsers
```

`hyprctl dispatch X` wraps its argument as `hl.dispatch(X)`, so `X` has to come
from the `hl.dsp.*` namespace:

```bash
hyprctl -i <sig> dispatch 'hl.dsp.focus({workspace=2})'
```

## Discovering the API

`hyprctl repl` prints return values; `hyprctl eval` runs code but prints only
`ok`, which makes it useless for exploration.

```bash
hyprctl repl 'local t={} for k,v in pairs(hl.dsp) do t[#t+1]=k end table.sort(t) return table.concat(t,", ")'
```

gives: `cursor, dpms, event, exec_cmd, exec_raw, exit, focus, force_idle,
force_renderer_reload, global, group, layout, no_op, pass,
release_input_capture, send_key_state, send_shortcut, submap, window,
workspace`.

Calling one incorrectly prints what it expected, which is the quickest way to
learn a signature. Note `hl.dsp.workspace.change_id` *renames* a workspace — it
does not switch to one. Focus is what switches.

## Relative selectors are unusable for edge detection

`e+1` **wraps around** (ws2 → ws3 → ws1) and walks onto other monitors. Any
feature that depends on noticing the first or last workspace — such as "swipe
left off the front to leave" — must compute absolute ids and filter by
`monitor`.

## `dpms` toggles, and ignores the argument you expect

```bash
hyprctl dispatch 'hl.dsp.dpms({on=true})'   # True → False → True → False
hyprctl dispatch 'dpms on'                  # does not parse under Lua
```

The `on` key is accepted and ignored; every call toggles. Used as a wake call
this blanks the display on every second use, which looks like faulty hardware.
Read `dpmsStatus` from `hyprctl monitors -j` first and only toggle when the
output is actually asleep.

Waking matters here: the output sleeps while the shared monitor is showing the
other machine, so switching the input back lands on a display sending no
picture. The workspaces switch correctly underneath and the screen stays dark.

## Focusing a workspace creates it

Focusing an id that does not exist creates that workspace on the active
monitor. That is what makes "spare" Spaces work — swiping into one brings a new
workspace into being. Spare ids must skip anything in use on *another* output,
since focusing such a workspace drags focus to that monitor instead.

## Always select the instance explicitly

More than one Hyprland can be running. `hyprctl -i <signature>` picks one, and
the signature should be resolved by which instance actually drives the target
monitor — never by recency or position:

```bash
for d in /run/user/1001/hypr/*/; do
  sig=$(basename "$d")
  hyprctl -i "$sig" monitors -j 2>/dev/null | grep -q HDMI-A-1 && echo "$sig"
done
```

The runtime directory keeps a stale entry for every compositor ever started
(20+ here), so probing dead ones is normal and should not be logged as an
error.
