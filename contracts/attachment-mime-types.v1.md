# Attachment image MIME extensions, version 1

Evidence class: source-read of published package data on 2026-10-30, not a
live CloudRoom observation. The installed CloudRoom package version was unknown.
The image-typed filename extensions are the union of `mime-types` 2.1.35
(`mime-db` 1.52.0: 98 extensions) and 3.0.2 (`mime-db` 1.54.0: 106 extensions).
The union has 107 sorted, unique, lowercase extensions.

Only 3.0.2 adds `btf dib dng dpx jaii jais jfif jpgm jxl`; only 2.1.35 has
`hsj2`. Taking the union refuses a potentially oversized file before upload
rather than letting a missing extension reach the provider's lower image cap.
The precise live package version and its limits still require a live check.

`IMAGE_TYPED_EXTENSIONS` uses this set for the 10 MiB image limit, including
image-typed names sent as files; other file names use the 25 MiB file limit.
This record changes neither cap nor the separate content/name matching rules.
AP2 independently pins the literal set and compares the core with it and with
this public record. Updating the record is an explicit contract change.

3ds apng avci avcs avif azv b16 bmp btf btif cgm cmx dds dib djv djvu dng dpx drle dwg dxf emf exr fbs fh fh4 fh5 fh7 fhc fits fpx fst g3 gif heic heics heif heifs hej2 hsj2 ico ief jaii jais jfif jhc jls jng jp2 jpe jpeg jpf jpg jpg2 jpgm jph jpm jpx jxl jxr jxra jxrs jxs jxsc jxsi jxss ktx ktx2 mdi mmr npx pbm pct pcx pgm pic png pnm ppm psd pti ras rgb rlc sgi sid svg svgz t38 tap tfx tga tif tiff uvg uvi uvvg uvvi vtf wbmp wdp webp wmf xbm xif xpm xwd
