# macOS Spaces and screens

## Two coordinate systems, disagreeing about up

| | origin | y grows |
|---|---|---|
| CoreGraphics (event locations) | top-left of the main display | downwards |
| Cocoa (`NSScreen.frame`) | bottom-left of the main display | upwards |

Comparing one against the other appears to work whenever displays are arranged
horizontally, and silently picks the wrong display as soon as they are stacked
vertically — which is this setup: the 49" sits at Cocoa `(0,0)`, and the shared
34" is *above* it at Cocoa `y=1440`, meaning CG `y=-1440`.

```python
def cg_point_in_frame(x, y, frame, main_height):
    cocoa_y = main_height - y
    return (frame.origin.x <= x < frame.origin.x + frame.size.width
            and frame.origin.y <= cocoa_y < frame.origin.y + frame.size.height)
```

`main_height` is `NSScreen.screens()[0].frame().size.height` — index 0 is the
screen holding the origin, not necessarily the one you care about.

## A window's content rect is measured from its screen

`initWithContentRect:styleMask:backing:defer:screen:` interprets the rect
relative to the **specified screen's** origin, not the global one. Passing a
global frame therefore doubles the offset on any display not at `(0,0)`:

```
screen at (787, 1440) + frame origin (787, 1440) → window at (1574, 2048)
```

The window then hangs off the display, and `toggleFullScreen_` puts its Space
on whichever display holds most of it — so a Space silently opens on the wrong
monitor. Build at the origin and position afterwards, where coordinates are
global:

```python
w = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_screen_(
    NSMakeRect(0, 0, frame.size.width, frame.size.height), style, backing, False, screen)
w.setFrame_display_(frame, False)
```

It is worth logging which screen a window actually landed on: from the app's
side a misplaced Space is invisible, while to the person using it it is glaring.

## `NSScreen` objects are not identity-stable

PyObjC hands back a fresh proxy for the same display on every call, so `is`
never matches and `==` is unreliable. Compare by frame.

## Displays can have their own Spaces

`defaults read com.apple.spaces spans-displays` — `0` means each display keeps
its own active Space, which is the default.

The consequence: `NSWindow.isOnActiveSpace` tells you a window's Space is
frontmost **on its own display**. It says nothing about where the user is. A
Space can sit frontmost on one monitor for hours while the person works on
another.

An earlier version used that as the signal for "the user is here" and so held
the keyboard captured indefinitely while they were on the other display. Space
membership answers *what is displayed*; it is not a proxy for attention. Here
the pointer answers that instead.

## Full-screen Spaces are asynchronous and ordered by creation

`toggleFullScreen_` animates and completes later. Building several in a row
requires sequencing on `windowDidEnterFullScreen:`, one at a time — starting
the next before the previous settles gets them out of order or refused.

They appear in creation order, after the user's existing Spaces, which is what
makes a "strip" possible. A person can still reorder them in Mission Control;
mapping by window identity rather than position keeps that correct, though the
left-to-right order then no longer matches.

Creating a full-screen Space also switches to it, so a run that builds N Spaces
ends up on the last one. Explicitly returning to the first afterwards makes
launch behaviour predictable.


## Mission Control will not show you a per-Space title

A full-screen Space is labelled with the *application name* of the process
owning its window. Asking macOS what it stores per Space makes the reason
plain - via the private `CGSCopyManagedDisplaySpaces`:

    id=881 type=4 keys=['ManagedSpaceID','TileLayoutManager','WallSpace',
                        'fs_wid','id64','pid','type']

A `pid` and a window id. **No name field exists**, so there is nothing to set.
Mission Control resolves the pid to an app and shows its name, which is why the
label tracked `python` and then `dmswitch` while the window titles - correctly
set, and visible in `CGWindowListCopyWindowInfo` - were ignored throughout.

Since the label follows the pid, genuinely per-Space names would need a
separate process per Space, and bundle names are static anyway, so a title that
changes as you work still could not be shown.

**What does work: draw the title into the window.** The Space thumbnail is a
picture of your window, and you own every pixel of it. Mission Control shrinks
a 3440px-wide Space by roughly 17x, so the text has to be enormous - about
0.11 of the window height, ~158pt here, reducing to a readable ~9pt.

That would be absurd in a window anyone looked at. This one is never looked at:
while it is on screen the monitor is displaying the other machine. Worth
remembering that a window nobody sees at full size is free to be shaped
entirely around how it appears in a thumbnail.
