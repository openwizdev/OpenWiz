//! AP1 Kind from bytes. PNG, JPEG, GIF and WebP are images; HEIC and HEIF
//! are refused with the stated reason; everything else is a file. A wrong
//! extension never changes the kind: when the name and the bytes disagree
//! the file is refused (B-5), and a declared MIME type can't reach the
//! decision at all.

use openwiz_core::attachment::{FailReason, Kind, SNIFF_BYTES, SafeName, classify};

use crate::support::*;

/// The decision's whole input is the safe name and the bytes. A declared
/// MIME type (the browser's, or the CLI's guess) has no way in: this line
/// stops compiling if one is ever added.
const _SIGNATURE: fn(&SafeName, &[u8]) -> Result<Kind, FailReason> = classify;

#[test]
fn ap1_kind_contracts_preserve_all_original_cases() {
    let cases: [(&str, fn()); 12] = [
        ("a_partial_brand_is_unclear", a_partial_brand_is_unclear),
        (
            "a_wrong_extension_never_changes_the_kind",
            a_wrong_extension_never_changes_the_kind,
        ),
        (
            "an_inconclusive_ftyp_is_refused",
            an_inconclusive_ftyp_is_refused,
        ),
        ("avif_stays_a_file", avif_stays_a_file),
        ("everything_else_is_a_file", everything_else_is_a_file),
        (
            "heic_and_heif_are_refused_with_the_stated_reason",
            heic_and_heif_are_refused_with_the_stated_reason,
        ),
        (
            "heif_is_found_in_any_brand_position_and_header_form",
            heif_is_found_in_any_brand_position_and_header_form,
        ),
        (
            "iso_box_sizes_include_the_high_order_bytes",
            iso_box_sizes_include_the_high_order_bytes,
        ),
        (
            "iso_minor_versions_are_not_compatible_brands",
            iso_minor_versions_are_not_compatible_brands,
        ),
        (
            "png_jpeg_gif_and_webp_are_images_by_their_bytes",
            png_jpeg_gif_and_webp_are_images_by_their_bytes,
        ),
        (
            "the_kind_comes_from_the_first_bytes_only",
            the_kind_comes_from_the_first_bytes_only,
        ),
        (
            "zero_size_iso_boxes_require_eof_below_the_sniff_bound",
            zero_size_iso_boxes_require_eof_below_the_sniff_bound,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: ap01_kind::{name}");
        proof();
    }
}

fn png_jpeg_gif_and_webp_are_images_by_their_bytes() {
    for (file, bytes) in [
        ("synthetic.png", PNG),
        ("synthetic.PNG", PNG),
        ("synthetic.jpg", JPEG),
        ("synthetic.jpeg", JPEG),
        ("synthetic.JPE", JPEG),
        ("synthetic.gif", GIF87),
        ("synthetic.gif", GIF89),
        ("synthetic.webp", WEBP),
    ] {
        assert_eq!(classify(&name(file), bytes), Ok(Kind::Image), "{file}");
    }
}

fn heic_and_heif_are_refused_with_the_stated_reason() {
    for (file, bytes) in [
        ("synthetic.heic", heic()),
        ("synthetic.heif", heif()),
        ("synthetic.HEIC", ftyp(b"heix", &[b"mif1"])),
        ("synthetic.heics", ftyp(b"hevc", &[b"msf1"])),
        // HEIC bytes under another image's name: still HEIC.
        ("synthetic.jpg", heic()),
        ("synthetic.txt", heif()),
    ] {
        assert_eq!(
            classify(&name(file), &bytes),
            Err(FailReason::UnsupportedHeif),
            "{file}"
        );
    }
    assert_eq!(
        FailReason::UnsupportedHeif.message(),
        "HEIC/HEIF images aren't supported. Nothing was converted"
    );
}

fn everything_else_is_a_file() {
    for (file, bytes) in [
        ("synthetic.svg", SVG.to_vec()),
        ("synthetic.html", HTML.to_vec()),
        ("synthetic.bmp", BMP.to_vec()),
        ("synthetic.tiff", TIFF.to_vec()),
        ("synthetic.pdf", PDF.to_vec()),
        // B-4: a ZIP is attached unchanged, as a file, never unpacked.
        ("synthetic.zip", ZIP.to_vec()),
        ("synthetic.txt", TEXT.to_vec()),
        ("synthetic", TEXT.to_vec()),
        ("synthetic.avif", avif()),
        ("synthetic.bin", Vec::new()),
        ("synthetic.bin", vec![0x89]),
    ] {
        assert_eq!(classify(&name(file), &bytes), Ok(Kind::File), "{file}");
    }
}

fn a_wrong_extension_never_changes_the_kind() {
    // An image under another name is refused, never sent as a file
    // (CloudRoom types by the extension, F4).
    for (file, bytes) in [
        ("synthetic.jpg", PNG),
        ("synthetic.png", JPEG),
        ("synthetic.webp", GIF89),
        ("synthetic.gif", WEBP),
        ("synthetic.txt", PNG),
        ("synthetic.pdf", JPEG),
        ("synthetic.svg", PNG),
        ("synthetic", PNG),
        ("synthetic.png.txt", PNG),
    ] {
        assert_eq!(
            classify(&name(file), bytes),
            Err(FailReason::ExtensionMismatch),
            "{file}"
        );
    }
    // A non-image under an image's name is refused, never sent as an image.
    for (file, bytes) in [
        ("synthetic.png", TEXT),
        ("synthetic.jpg", PDF),
        ("synthetic.gif", ZIP),
        ("synthetic.webp", SVG),
        ("synthetic.heic", TEXT),
        ("synthetic.txt.png", TEXT),
    ] {
        assert_eq!(
            classify(&name(file), bytes),
            Err(FailReason::ExtensionMismatch),
            "{file}"
        );
    }
    assert!(!FailReason::ExtensionMismatch.message().is_empty());
}

fn the_kind_comes_from_the_first_bytes_only() {
    // The magic must be at the start: the same bytes later in the file
    // don't make an image.
    let mut late = TEXT.to_vec();
    late.extend_from_slice(PNG);
    assert_eq!(classify(&name("synthetic.txt"), &late), Ok(Kind::File));
    // A truncated signature isn't an image.
    assert_eq!(classify(&name("synthetic.bin"), &PNG[..7]), Ok(Kind::File));
    assert_eq!(
        classify(&name("synthetic.png"), &PNG[..7]),
        Err(FailReason::ExtensionMismatch)
    );
    // RIFF that isn't WebP (a WAV) is a file.
    assert_eq!(
        classify(&name("synthetic.wav"), b"RIFF\x24\0\0\0WAVEfmt "),
        Ok(Kind::File)
    );
    // A whole file and its first bytes give the same answer.
    let whole = padded(PNG, 4096);
    assert_eq!(
        classify(&name("synthetic.png"), &whole),
        classify(&name("synthetic.png"), PNG)
    );
}

/// An `ftyp` box with a 64-bit size (`size` = 1, then the real size in the
/// next 8 bytes), as libheif parses it.
fn ftyp_extended(major: &[u8; 4], compatible: &[&[u8; 4]]) -> Vec<u8> {
    let size = 24 + 4 * compatible.len();
    let mut bytes = 1u32.to_be_bytes().to_vec();
    bytes.extend_from_slice(b"ftyp");
    bytes.extend_from_slice(&u64::try_from(size).unwrap().to_be_bytes());
    bytes.extend_from_slice(major);
    bytes.extend_from_slice(&[0, 0, 0, 0]);
    for brand in compatible {
        bytes.extend_from_slice(*brand);
    }
    bytes.extend_from_slice(b"\0\0\0\x08meta");
    bytes
}

/// Sol round 1, finding 2: HEIF brands only in the compatible list, and a
/// 64-bit box header, were both taken as files.
fn heif_is_found_in_any_brand_position_and_header_form() {
    for (what, bytes) in [
        (
            "major isom, compatible mif1 heic",
            ftyp(b"isom", &[b"mif1", b"heic"]),
        ),
        ("major isom, compatible heix", ftyp(b"isom", &[b"heix"])),
        (
            "64-bit size, major heic",
            ftyp_extended(b"heic", &[b"mif1", b"heic"]),
        ),
        (
            "64-bit size, major isom, compatible heic",
            ftyp_extended(b"isom", &[b"heic"]),
        ),
        (
            "64-bit size, major mif1",
            ftyp_extended(b"mif1", &[b"mif1"]),
        ),
    ] {
        for file in ["synthetic.bin", "synthetic.heic", "synthetic.jpg"] {
            assert_eq!(
                classify(&name(file), &bytes),
                Err(FailReason::UnsupportedHeif),
                "{what}, as {file}"
            );
        }
    }
}

/// AVIF is HEIF's container with AV1 inside: a file, not a refused HEIC,
/// whichever position its brand is in.
fn avif_stays_a_file() {
    for (what, bytes) in [
        ("major avif", ftyp(b"avif", &[b"avif", b"mif1", b"miaf"])),
        (
            "major mif1, compatible avif",
            ftyp(b"mif1", &[b"avif", b"mif1", b"miaf"]),
        ),
        (
            "major msf1, compatible avis",
            ftyp(b"msf1", &[b"avis", b"msf1"]),
        ),
        (
            "64-bit size, major avif",
            ftyp_extended(b"avif", &[b"mif1"]),
        ),
    ] {
        assert_eq!(
            classify(&name("synthetic.avif"), &bytes),
            Ok(Kind::File),
            "{what}"
        );
    }
    // Other ISO media files are files too.
    let mp4 = ftyp(b"isom", &[b"isom", b"iso2", b"avc1", b"mp41"]);
    assert_eq!(classify(&name("synthetic.mp4"), &mp4), Ok(Kind::File));
}

/// What can't be decided is refused, never let through as a file.
fn an_inconclusive_ftyp_is_refused() {
    assert!(FailReason::TypeUnclear.message().contains("HEIC/HEIF"));
    let mut huge = ftyp(b"isom", &[b"isom"]);
    huge[..4].copy_from_slice(&100_000u32.to_be_bytes());
    let mut cut = ftyp(b"isom", &[b"mif1", b"heic"]);
    cut[..4].copy_from_slice(&64u32.to_be_bytes());
    cut.truncate(20);
    let mut tiny = ftyp(b"heic", &[]);
    tiny[..4].copy_from_slice(&10u32.to_be_bytes());
    for (what, bytes) in [
        (
            "HEVC and AV1 brands together",
            ftyp(b"mif1", &[b"heic", b"avif"]),
        ),
        ("a box larger than the bytes read", huge),
        ("a box cut short by the end of the file", cut),
        ("a box too small for its brand", tiny),
        (
            "a 64-bit size cut short",
            ftyp_extended(b"heic", &[])[..12].to_vec(),
        ),
    ] {
        for file in ["synthetic.bin", "synthetic.mp4", "synthetic.heic"] {
            assert_eq!(
                classify(&name(file), &bytes),
                Err(FailReason::TypeUnclear),
                "{what}, as {file}"
            );
        }
    }
}

fn iso_box_sizes_include_the_high_order_bytes() {
    // Each declared size ends in the length of the supplied prefix. Dropping
    // the higher bytes would make these truncated boxes look complete.
    let mut short = b"\x01\0\0\x10ftypisom\0\0\0\0".to_vec();
    let mut extended = b"\0\0\0\x01ftyp\0\0\0\x01\0\0\0\x18isom\0\0\0\0".to_vec();
    for bytes in [&short, &extended] {
        assert_eq!(
            classify(&name("synthetic.mp4"), bytes),
            Err(FailReason::TypeUnclear),
            "truncated box: {bytes:?}"
        );
    }

    // Complete boxes with multi-byte lengths are still ordinary files.
    short[..4].copy_from_slice(&272u32.to_be_bytes());
    short.resize(272, 0);
    extended[8..16].copy_from_slice(&280u64.to_be_bytes());
    extended.resize(280, 0);
    for bytes in [&short, &extended] {
        assert_eq!(classify(&name("synthetic.mp4"), bytes), Ok(Kind::File));
    }
}

fn zero_size_iso_boxes_require_eof_below_the_sniff_bound() {
    for (len, expected) in [
        (16, Ok(Kind::File)),
        (SNIFF_BYTES - 4, Ok(Kind::File)),
        (SNIFF_BYTES, Err(FailReason::TypeUnclear)),
    ] {
        // Size zero extends to EOF. Whole four-byte padding keeps every
        // compatible-brand slot complete, so only EOF certainty differs.
        let mut bytes = b"\0\0\0\0ftypisom\0\0\0\0".to_vec();
        bytes.resize(len, 0);
        assert_eq!(
            classify(&name("synthetic.mp4"), &bytes),
            expected,
            "zero-size box, {len} bytes"
        );
    }
}

fn iso_minor_versions_are_not_compatible_brands() {
    for (major, minor, expected) in [
        (b"isom", b"heic", Ok(Kind::File)),
        (b"isom", b"avif", Ok(Kind::File)),
        (b"heic", b"avif", Err(FailReason::UnsupportedHeif)),
    ] {
        for (form, mut bytes, minor_at) in [
            ("32-bit", ftyp(major, &[]), 12..16),
            ("64-bit", ftyp_extended(major, &[]), 20..24),
        ] {
            // Synthetic version words deliberately spell known brands.
            bytes[minor_at].copy_from_slice(minor);
            assert_eq!(
                classify(&name("synthetic.bin"), &bytes),
                expected,
                "{form}, major {major:?}, minor {minor:?}"
            );
        }
    }
}

/// Sol round 2, finding 2: bytes after the last whole brand were dropped,
/// so a cut-off `hei` brand didn't count. A box whose brands aren't whole
/// 4-byte brands is unclear, in both header forms, for every remainder.
fn a_partial_brand_is_unclear() {
    let mut accepted = Vec::new();
    for tail in [&b"h"[..], b"he", b"hei"] {
        for (form, mut bytes, size_at) in [
            ("32-bit", ftyp(b"isom", &[]), 0..4),
            ("64-bit", ftyp_extended(b"isom", &[]), 8..16),
            (
                "32-bit, after a whole brand",
                ftyp(b"isom", &[b"isom"]),
                0..4,
            ),
        ] {
            // The box ends after the tail: cut the trailing `meta` box,
            // add the tail, then set the box's size to match.
            bytes.truncate(bytes.len() - 8);
            bytes.extend_from_slice(tail);
            let size = bytes.len() as u64;
            if size_at.len() == 4 {
                bytes[size_at].copy_from_slice(&u32::try_from(size).unwrap().to_be_bytes());
            } else {
                bytes[size_at].copy_from_slice(&size.to_be_bytes());
            }
            for file in ["synthetic.bin", "synthetic.mp4"] {
                let result = classify(&name(file), &bytes);
                if result != Err(FailReason::TypeUnclear) {
                    accepted.push(format!(
                        "{form}, tail {:?} ({} bytes), as {file}: {result:?}",
                        String::from_utf8_lossy(tail),
                        bytes.len()
                    ));
                }
            }
        }
    }
    // The case Sol probed: 19 bytes, major isom, minor 0, then `hei`.
    let mut sol = 19u32.to_be_bytes().to_vec();
    sol.extend_from_slice(b"ftypisom\0\0\0\0hei");
    assert_eq!(sol.len(), 19);
    let result = classify(&name("synthetic.bin"), &sol);
    if result != Err(FailReason::TypeUnclear) {
        accepted.push(format!("Sol's 19-byte box: {result:?}"));
    }
    assert!(
        accepted.is_empty(),
        "{} not unclear:\n{}",
        accepted.len(),
        accepted.join("\n")
    );
}
