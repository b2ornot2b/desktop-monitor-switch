# Learnings

Things this project cost real time to find out, kept so they only cost it once.
Each file in `learnings.d/` covers one area.

| file | what it saves you from |
|---|---|
| [silent-failures.md](learnings.d/silent-failures.md) | four separate layers here report success and do nothing |
| [debugging-methodology.md](learnings.d/debugging-methodology.md) | hours lost to a broken measurement rather than a broken system |
| [macos-event-taps.md](learnings.d/macos-event-taps.md) | permissions, suppression, and why gestures cannot be intercepted |
| [macos-spaces-and-screens.md](learnings.d/macos-spaces-and-screens.md) | two coordinate systems, per-display Spaces, off-origin displays |
| [pyobjc.md](learnings.d/pyobjc.md) | selectors, run loops, signals, and an app that could not be quit |
| [hyprland-lua-api.md](learnings.d/hyprland-lua-api.md) | Hyprland 0.56's Lua dispatchers, and a dpms call that toggles |
| [ydotool-uinput.md](learnings.d/ydotool-uinput.md) | injecting input under Wayland, and the flags that fail quietly |
| [deskflow-dead-end.md](learnings.d/deskflow-dead-end.md) | why the obvious off-the-shelf answer does not work here |

## The short version

If you read nothing else:

1. **Exit code 0 proves nothing in this stack.** Verify the observable effect.
2. **Check your instrument before doubting the system.** The longest detour in
   this project was a correct system measured wrongly.
3. **Which machine shows and which machine receives are different questions.**
   The monitor follows the Space; input follows the pointer.
4. **Never leave input captured without an escape.** Pointer to the other
   display, swipe off the strip, panic key, Cmd+Q.
