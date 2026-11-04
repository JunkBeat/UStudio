# The sdf_map.txt file: format and examples

Each line of the map sets up one or more SDF fonts: **left of the “=” sign** go the names of the SDF fonts, comma-separated; **on the right** — the vector font to take the characters from and, if you like, settings, comma-separated.

A quick example:

```
"Arial SDF" = arial.ttf
"Pixel SDF", "Pixel SDF Bold" = pixel.ttf, mode=full, chars="АБВ"
```

#### Main settings of the mapping file

| Name | Value | What it does |
|---|---|---|
| `mode` | `add`, `replace`, `full` | Generation mode:<br>• **add** — add characters;<br>• **replace** — add + replace characters;<br>• **full** — replace the whole font.<br><small>*(default `add`)*</small> |
| `chars` | a string or the name of a<br>text file with the characters | The characters to generate |

#### Settings for the `full` mode only

| Name | Value | What it does |
|---|---|---|
| `size` | a number or `fit` | Font size: any number, or `fit`, which means “Fit the texture”. |
| `range` | a number | Edge sharpness.<br>• *For pixel fonts ~4px;*<br>• *For smooth fonts ~10px* |
| `match_height` | `on` or `off` | Whether to match the letters' height to the original.<br><small>*(default `on`)*</small> |
| `add_chars` | `on` or `off` | Whether to also process characters the SDF font has but `chars` does not list.<br><small>*(default `on`)*</small> |
| `atlas` | numbers like<br>1024x512 | Set the atlas size exactly *(usually not needed)*. |

<small>*If `size` and `range` are not given, the SDF font's own values are used.*</small>

#### Shared settings — the `default:` line

The `default:` line *(one per file, anywhere in it)* sets the settings for the lines that
don't give them. A line's own setting always wins over it. The `full`-mode settings listed in the `default` line apply only to lines whose final mode is `mode=full`.
<br><br>How it works:

```
default: size=48, range=6

# This font gets size=48 and range=6 from default
"Title SDF" = title.ttf, mode=full

# The default add mode: size/range from default are ignored
"Body SDF"  = body.ttf

# ERROR: size cannot be used with the add mode
"Menu SDF"  = menu.ttf, mode=add, size=40
```

#### How to name the target SDF

- **The name of the TMP_FontAsset object** — generates for every SDF font with that name.
<br>*Example: `"Arial SDF"`.*
- **A reference** — source + PathID.
<br>*Example: `level0:55`.*

#### More about `chars=`

- `chars="abc"` — the characters in double quotes.
- `chars=my_chars.txt` — the name of a text file with the characters, without quotes (or a path relative to the mapping file, like `chars=sub/x.txt`).
Nothing needs escaping in the text file. Line breaks
and tabs are skipped, repeats don't matter.
- If `chars` is set neither in the line nor in `default`, the characters come from a `chars.txt` file in the same folder as the mapping file. If there is none either, it is an error.

Special characters inside `chars="..."`:

| You write | You get |
|---|---|
| `\"` | A double quote |
| `\\` | A backslash |
| `\uXXXX` | A character by its code, 4 digits (`\u00AB` — «) |
| `\UXXXXXXXX` | A character by its code, 8 digits (emoji and the like) |

Any other backslash is an error.

#### Other notes

- `sdf_map.txt` and the character files must be **UTF-8** (with or without BOM). In “ANSI” / Windows-1251 encoding, Cyrillic is read wrongly.
- Lines that start with `#` are comments and are skipped.

### Examples

*Reminder:*

- *If no generation mode is given, `add` is used.*
- *If `chars` is not given, the characters come from `chars.txt`.*

**1.** Add the missing characters to one SDF font:

```
"Arial SDF" = arial.ttf
```

**2.** Add the missing characters from one ttf to many SDF fonts:

```
"Arial SDF", "Arial SDF Bold", "Arial SDF Title" = arial.ttf
```

**3.** Each SDF font has its own source, the characters and mode are shared:

```
default: mode=add, chars=cyrillic.txt
"Body SDF" = roboto.ttf
"Title SDF" = "fonts/Bebas Neue.ttf"
"Menu SDF" = "fonts/Open Sans, Bold.ttf"
```

**4.** Replace an SDF font, fitting the characters into the texture:

```
"Pixel SDF" = pixel.ttf, mode=full, size=fit, chars=cyrillic.txt
```

**5.** Replace an SDF font with a set size, no height matching, soft edges:

```
"Main SDF" = main.ttf, mode=full, size=48, match_height=off, range=8
```

**6.** Generate in add mode, naming the TMP_FontAsset by a reference instead of its name:

```
level0:55 = main.ttf
```

**7.** Quotes and special characters to generate:

```
"Text SDF" = text.ttf, chars="«»„“”—–…\"'"
"Icons SDF" = icons.ttf, chars="\u2605\u2606\U0001F600"
```

**8.** Replace the title SDF font completely, generate the others in add mode:

```
default: mode=add, chars=cyrillic.txt
"Title SDF" = title.ttf, mode=full, size=fit, range=6
"Body SDF", "Body SDF Italic" = body.ttf
```
