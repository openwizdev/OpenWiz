use std::fmt;
use std::time::Duration;

use serde::de::{self, MapAccess, Unexpected, Visitor};
use serde::{Deserialize, Deserializer, Serialize, Serializer};

pub const IMAGE_MAX_BYTES: u64 = 10 * 1024 * 1024;

pub const FILE_MAX_BYTES: u64 = 25 * 1024 * 1024;

pub const CLOUDROOM_NAME_MAX_BYTES: usize = 200;

pub const CLOUDROOM_SUFFIX_MAX_BYTES: usize = 21;

pub const SAFE_NAME_MAX_BYTES: usize = CLOUDROOM_NAME_MAX_BYTES - CLOUDROOM_SUFFIX_MAX_BYTES;

pub const ATTACHMENT_ID_MAX_LEN: usize = 64;

pub const SNIFF_BYTES: usize = 4096;

pub const UNSENT_TTL: Duration = Duration::from_secs(24 * 60 * 60);

pub const IMAGE_TYPED_EXTENSIONS: &[&str] = &[
    "3ds", "apng", "avci", "avcs", "avif", "azv", "b16", "bmp", "btf", "btif", "cgm", "cmx", "dds",
    "dib", "djv", "djvu", "dng", "dpx", "drle", "dwg", "dxf", "emf", "exr", "fbs", "fh", "fh4",
    "fh5", "fh7", "fhc", "fits", "fpx", "fst", "g3", "gif", "heic", "heics", "heif", "heifs",
    "hej2", "hsj2", "ico", "ief", "jaii", "jais", "jfif", "jhc", "jls", "jng", "jp2", "jpe",
    "jpeg", "jpf", "jpg", "jpg2", "jpgm", "jph", "jpm", "jpx", "jxl", "jxr", "jxra", "jxrs", "jxs",
    "jxsc", "jxsi", "jxss", "ktx", "ktx2", "mdi", "mmr", "npx", "pbm", "pct", "pcx", "pgm", "pic",
    "png", "pnm", "ppm", "psd", "pti", "ras", "rgb", "rlc", "sgi", "sid", "svg", "svgz", "t38",
    "tap", "tfx", "tga", "tif", "tiff", "uvg", "uvi", "uvvg", "uvvi", "vtf", "wbmp", "wdp", "webp",
    "wmf", "xbm", "xif", "xpm", "xwd",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Kind {
    Image,
    File,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum FailReason {
    UnsupportedHeif,
    TypeUnclear,
    ExtensionMismatch,
    ImageTooLarge,
    FileTooLarge,
    ImageTypedFileTooLarge,
    Folder,
    LowDisk,
    SizeMismatch,
    ConnectionLost,
    SignedOut,
    Unreadable,
}

trait Labels: Copy + PartialEq + 'static {
    fn labels() -> &'static [(&'static str, Self)];

    fn label(self) -> &'static str {
        Self::labels()
            .iter()
            .find(|(_, value)| *value == self)
            .map(|(label, _)| *label)
            .unwrap_or_default()
    }
}

struct LabelVisitor<T>(std::marker::PhantomData<T>);

impl<T: Labels> Visitor<'_> for LabelVisitor<T> {
    type Value = T;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let labels: Vec<&str> = T::labels().iter().map(|(label, _)| *label).collect();
        write!(f, "one of the strings {}", labels.join(", "))
    }

    fn visit_str<E: de::Error>(self, text: &str) -> Result<T, E> {
        T::labels()
            .iter()
            .find(|(label, _)| *label == text)
            .map(|(_, value)| *value)
            .ok_or_else(|| E::invalid_value(Unexpected::Str(text), &self))
    }
}

fn read_label<'de, D: Deserializer<'de>, T: Labels>(d: D) -> Result<T, D::Error> {
    d.deserialize_str(LabelVisitor(std::marker::PhantomData))
}

impl Labels for Kind {
    fn labels() -> &'static [(&'static str, Self)] {
        &[("image", Self::Image), ("file", Self::File)]
    }
}

impl Kind {
    pub fn labels() -> &'static [(&'static str, Self)] {
        <Self as Labels>::labels()
    }
}

impl Serialize for Kind {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(self.label())
    }
}

impl<'de> Deserialize<'de> for Kind {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        read_label(d)
    }
}

impl Labels for FailReason {
    fn labels() -> &'static [(&'static str, Self)] {
        &[
            ("unsupported_heif", Self::UnsupportedHeif),
            ("type_unclear", Self::TypeUnclear),
            ("extension_mismatch", Self::ExtensionMismatch),
            ("image_too_large", Self::ImageTooLarge),
            ("file_too_large", Self::FileTooLarge),
            ("image_typed_file_too_large", Self::ImageTypedFileTooLarge),
            ("folder", Self::Folder),
            ("low_disk", Self::LowDisk),
            ("size_mismatch", Self::SizeMismatch),
            ("connection_lost", Self::ConnectionLost),
            ("signed_out", Self::SignedOut),
            ("unreadable", Self::Unreadable),
        ]
    }
}

impl Serialize for FailReason {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(self.label())
    }
}

impl<'de> Deserialize<'de> for FailReason {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        read_label(d)
    }
}

impl FailReason {
    pub fn labels() -> &'static [(&'static str, Self)] {
        <Self as Labels>::labels()
    }

    pub fn message(self) -> &'static str {
        match self {
            Self::UnsupportedHeif => "HEIC/HEIF images aren't supported. Nothing was converted",
            Self::TypeUnclear => {
                "The file's first bytes don't show whether it is a HEIC/HEIF image, so it wasn't \
                 attached"
            }
            Self::ExtensionMismatch => {
                "The file's extension doesn't match its content. Nothing was renamed"
            }
            Self::ImageTooLarge => "CloudRoom accepts images up to 10 MiB",
            Self::FileTooLarge => "CloudRoom accepts files up to 25 MiB",
            Self::ImageTypedFileTooLarge => {
                "CloudRoom treats a file with this extension as an image, and accepts images \
                 up to 10 MiB"
            }
            Self::Folder => "Folders aren't supported yet",
            Self::LowDisk => "Low disk: staging would leave less than 1 GiB free on the controller",
            Self::SizeMismatch => "The copy doesn't match the size or hash expected",
            Self::ConnectionLost => "The connection was lost before the whole file arrived",
            Self::SignedOut => "Signed out before the upload finished",
            Self::Unreadable => "The file couldn't be read",
        }
    }
}

impl fmt::Display for FailReason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.message())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InvalidAttachment(pub String);

impl fmt::Display for InvalidAttachment {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for InvalidAttachment {}

#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct SafeName(String);

impl SafeName {
    pub fn parse(name: &str) -> Result<Self, InvalidAttachment> {
        let valid = !name.is_empty()
            && name.len() <= SAFE_NAME_MAX_BYTES
            && !name.starts_with(['.', '-'])
            && name.chars().all(allowed);
        if valid {
            Ok(Self(name.to_owned()))
        } else {
            Err(InvalidAttachment(format!(
                "a safe name is 1 to {SAFE_NAME_MAX_BYTES} ASCII letters, digits, ., _ or -, \
                 not starting with . or -"
            )))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn extension(&self) -> Option<String> {
        let (_, extension) = self.0.rsplit_once('.')?;
        (!extension.is_empty()).then(|| extension.to_ascii_lowercase())
    }
}

fn allowed(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-')
}

impl TryFrom<String> for SafeName {
    type Error = InvalidAttachment;

    fn try_from(name: String) -> Result<Self, Self::Error> {
        Self::parse(&name)
    }
}

impl From<SafeName> for String {
    fn from(name: SafeName) -> Self {
        name.0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct AttachmentId(String);

impl AttachmentId {
    pub fn parse(id: &str) -> Result<Self, InvalidAttachment> {
        let valid = !id.is_empty()
            && id.len() <= ATTACHMENT_ID_MAX_LEN
            && id.as_bytes()[0].is_ascii_alphanumeric()
            && id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-');
        if valid {
            Ok(Self(id.to_owned()))
        } else {
            Err(InvalidAttachment(format!(
                "an attachment id is 1 to {ATTACHMENT_ID_MAX_LEN} ASCII letters, digits, _ or -, \
                 starting with a letter or digit"
            )))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl TryFrom<String> for AttachmentId {
    type Error = InvalidAttachment;

    fn try_from(id: String) -> Result<Self, Self::Error> {
        Self::parse(&id)
    }
}

impl From<AttachmentId> for String {
    fn from(id: AttachmentId) -> Self {
        id.0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct Sha256(String);

impl Sha256 {
    pub fn parse(hex: &str) -> Result<Self, InvalidAttachment> {
        let valid = hex.len() == 64 && hex.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'));
        if valid {
            Ok(Self(hex.to_owned()))
        } else {
            Err(InvalidAttachment(
                "a SHA-256 is 64 lowercase hex characters".to_owned(),
            ))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl TryFrom<String> for Sha256 {
    type Error = InvalidAttachment;

    fn try_from(hex: String) -> Result<Self, Self::Error> {
        Self::parse(&hex)
    }
}

impl From<Sha256> for String {
    fn from(hex: Sha256) -> Self {
        hex.0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct AttachmentRef {
    pub id: AttachmentId,
    pub sha256: Sha256,
    pub size_bytes: u64,
    pub kind: Kind,
    pub name: SafeName,
    pub display_name: String,
}

fn once<'de, A: MapAccess<'de>, T: Deserialize<'de>>(
    map: &mut A,
    slot: &mut Option<T>,
    key: &'static str,
) -> Result<(), A::Error> {
    if slot.is_some() {
        return Err(de::Error::duplicate_field(key));
    }
    *slot = Some(map.next_value()?);
    Ok(())
}

fn checked<E: de::Error, T>(
    text: Option<String>,
    key: &'static str,
    parse: fn(&str) -> Result<T, InvalidAttachment>,
) -> Result<T, E> {
    let text = text.ok_or_else(|| E::missing_field(key))?;
    parse(&text).map_err(|e| E::custom(format!("{key}: {e}")))
}

struct RefVisitor;

impl<'de> Visitor<'de> for RefVisitor {
    type Value = AttachmentRef;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("an attachment object")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<AttachmentRef, A::Error> {
        let (mut id, mut sha256, mut size_bytes, mut kind, mut name, mut display_name) =
            (None, None, None, None, None, None);
        while let Some(key) = map.next_key::<String>()? {
            match key.as_str() {
                "id" => once(&mut map, &mut id, "id")?,
                "sha256" => once(&mut map, &mut sha256, "sha256")?,
                "size_bytes" => once(&mut map, &mut size_bytes, "size_bytes")?,
                "kind" => once(&mut map, &mut kind, "kind")?,
                "name" => once(&mut map, &mut name, "name")?,
                "display_name" => once(&mut map, &mut display_name, "display_name")?,
                other => {
                    let keys = &["id", "sha256", "size_bytes", "kind", "name", "display_name"];
                    return Err(de::Error::unknown_field(other, keys));
                }
            }
        }
        Ok(AttachmentRef {
            id: checked(id, "id", AttachmentId::parse)?,
            sha256: checked(sha256, "sha256", Sha256::parse)?,
            size_bytes: size_bytes.ok_or_else(|| de::Error::missing_field("size_bytes"))?,
            kind: kind.ok_or_else(|| de::Error::missing_field("kind"))?,
            name: checked(name, "name", SafeName::parse)?,
            display_name: display_name.ok_or_else(|| de::Error::missing_field("display_name"))?,
        })
    }
}

impl<'de> Deserialize<'de> for AttachmentRef {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_map(RefVisitor)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Format {
    Png,
    Jpeg,
    Gif,
    Webp,
    Heif,
    Unclear,
    Other,
}

impl Format {
    fn sniff(bytes: &[u8]) -> Self {
        let head = &bytes[..bytes.len().min(SNIFF_BYTES)];
        if head.starts_with(b"\x89PNG\r\n\x1a\n") {
            Self::Png
        } else if head.starts_with(b"\xff\xd8\xff") {
            Self::Jpeg
        } else if head.starts_with(b"GIF87a") || head.starts_with(b"GIF89a") {
            Self::Gif
        } else if head.starts_with(b"RIFF") && head.get(8..12) == Some(b"WEBP") {
            Self::Webp
        } else if head.get(4..8) == Some(b"ftyp") {
            iso_media(head)
        } else {
            Self::Other
        }
    }

    fn extensions(self) -> &'static [&'static str] {
        match self {
            Self::Png => &["png"],
            Self::Jpeg => &["jpg", "jpeg", "jpe"],
            Self::Gif => &["gif"],
            Self::Webp => &["webp"],
            Self::Heif => &["heic", "heif", "heics", "heifs"],
            Self::Unclear | Self::Other => &[],
        }
    }
}

fn iso_media(head: &[u8]) -> Format {
    let be = |bytes: &[u8]| bytes.iter().fold(0u64, |n, &b| (n << 8) | u64::from(b));
    let (header, size) = match be(&head[..4]) {
        1 => match head.get(8..16) {
            Some(large) => (16, be(large)),
            None => return Format::Unclear,
        },
        0 if head.len() < SNIFF_BYTES => (8, head.len() as u64),
        0 => return Format::Unclear,
        size => (8, size),
    };
    let end = match usize::try_from(size) {
        Ok(end) if end >= header + 8 && end <= head.len() => end,
        _ => return Format::Unclear,
    };
    let major = &head[header..header + 4];
    let (compatible, partial) = head[header + 8..end].as_chunks::<4>();
    if !partial.is_empty() {
        return Format::Unclear;
    }
    let brands: Vec<&[u8]> = std::iter::once(major)
        .chain(compatible.iter().map(|b| &b[..]))
        .collect();
    let any = |set: &[&[u8; 4]]| brands.iter().any(|b| set.iter().any(|s| b == s));
    let hevc = any(&[
        b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"hevm", b"hevs",
    ]);
    let av1 = any(&[b"avif", b"avis"]);
    match (hevc, av1) {
        (true, true) => Format::Unclear,
        (true, false) => Format::Heif,
        (false, true) => Format::Other,
        (false, false) if any(&[b"mif1", b"msf1", b"mif2"]) => Format::Heif,
        (false, false) => Format::Other,
    }
}

pub fn classify(name: &SafeName, head: &[u8]) -> Result<Kind, FailReason> {
    let format = Format::sniff(head);
    match format {
        Format::Heif => return Err(FailReason::UnsupportedHeif),
        Format::Unclear => return Err(FailReason::TypeUnclear),
        _ => {}
    }
    let extension = name.extension().unwrap_or_default();
    let named = [
        Format::Png,
        Format::Jpeg,
        Format::Gif,
        Format::Webp,
        Format::Heif,
    ]
    .into_iter()
    .find(|f| f.extensions().contains(&extension.as_str()));
    match (format, named) {
        (Format::Other, None) => Ok(Kind::File),
        (Format::Other, Some(_)) => Err(FailReason::ExtensionMismatch),
        (image, Some(named)) if named == image => Ok(Kind::Image),
        _ => Err(FailReason::ExtensionMismatch),
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Limit {
    pub max_bytes: u64,
    pub over: FailReason,
}

impl Limit {
    pub fn admits(self, size_bytes: u64) -> Result<(), FailReason> {
        if size_bytes <= self.max_bytes {
            Ok(())
        } else {
            Err(self.over)
        }
    }
}

pub fn limit(kind: Kind, name: &SafeName) -> Limit {
    let image_typed = name
        .extension()
        .is_some_and(|e| IMAGE_TYPED_EXTENSIONS.binary_search(&e.as_str()).is_ok());
    match kind {
        Kind::Image => Limit {
            max_bytes: IMAGE_MAX_BYTES,
            over: FailReason::ImageTooLarge,
        },
        Kind::File if image_typed => Limit {
            max_bytes: IMAGE_MAX_BYTES,
            over: FailReason::ImageTypedFileTooLarge,
        },
        Kind::File => Limit {
            max_bytes: FILE_MAX_BYTES,
            over: FailReason::FileTooLarge,
        },
    }
}

pub fn check(name: &SafeName, head: &[u8], size_bytes: u64) -> Result<Kind, FailReason> {
    let kind = classify(name, head)?;
    limit(kind, name).admits(size_bytes)?;
    Ok(kind)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Claim {
    Unclaimed,
    Dispatching,
    Accepted,
    Failed,
    Uncertain,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stored {
    Partial,
    Ready { claim: Claim, age: Duration },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Retention {
    Keep,
    Delete(DeleteReason),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DeleteReason {
    Partial,
    Expired,
    Accepted,
}

pub fn retention(stored: Stored) -> Retention {
    match stored {
        Stored::Partial => Retention::Delete(DeleteReason::Partial),
        Stored::Ready { claim, age } => match claim {
            Claim::Accepted => Retention::Delete(DeleteReason::Accepted),
            Claim::Dispatching | Claim::Uncertain => Retention::Keep,
            Claim::Unclaimed | Claim::Failed if age >= UNSENT_TTL => {
                Retention::Delete(DeleteReason::Expired)
            }
            Claim::Unclaimed | Claim::Failed => Retention::Keep,
        },
    }
}

pub const STAGING_DIR: &str = "attachments";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StagedPath(String);

impl StagedPath {
    pub fn new(
        area: &std::path::Path,
        id: &AttachmentId,
        name: &SafeName,
    ) -> Result<Self, InvalidAttachment> {
        use std::path::Component;
        let refuse = || {
            Err(InvalidAttachment(format!(
                "a staged path is an absolute {STAGING_DIR} directory, with no . or .. \
                 component, in UTF-8 with no control character"
            )))
        };
        let Some(text) = area.to_str() else {
            return refuse();
        };
        let plain = text.strip_prefix('/').is_some_and(|rest| {
            rest.split('/')
                .all(|segment| !matches!(segment, "" | "." | ".."))
        }) && area
            .components()
            .all(|c| matches!(c, Component::RootDir | Component::Normal(_)));
        let named = area.file_name().is_some_and(|n| n == STAGING_DIR);
        if !plain || !named || text.chars().any(char::is_control) {
            return refuse();
        }
        Ok(Self(format!("{text}/{}/{}", id.as_str(), name.as_str())))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PromptAttachment {
    pub id: AttachmentId,
    pub sha256: Sha256,
    pub size_bytes: u64,
    pub kind: Kind,
    pub name: SafeName,
}

impl From<&AttachmentRef> for PromptAttachment {
    fn from(a: &AttachmentRef) -> Self {
        Self {
            id: a.id.clone(),
            sha256: a.sha256.clone(),
            size_bytes: a.size_bytes,
            kind: a.kind,
            name: a.name.clone(),
        }
    }
}

pub const PROMPT_ATTACHMENT_KEYS: &[&str] = &["id", "sha256", "size_bytes", "kind", "name"];

struct PromptAttachmentVisitor;

impl<'de> Visitor<'de> for PromptAttachmentVisitor {
    type Value = PromptAttachment;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a prompt attachment object")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<PromptAttachment, A::Error> {
        let (mut id, mut sha256, mut size_bytes, mut kind, mut name) =
            (None, None, None, None, None);
        while let Some(key) = map.next_key::<String>()? {
            match key.as_str() {
                "id" => once(&mut map, &mut id, "id")?,
                "sha256" => once(&mut map, &mut sha256, "sha256")?,
                "size_bytes" => once(&mut map, &mut size_bytes, "size_bytes")?,
                "kind" => once(&mut map, &mut kind, "kind")?,
                "name" => once(&mut map, &mut name, "name")?,
                other => return Err(de::Error::unknown_field(other, PROMPT_ATTACHMENT_KEYS)),
            }
        }
        Ok(PromptAttachment {
            id: checked(id, "id", AttachmentId::parse)?,
            sha256: checked(sha256, "sha256", Sha256::parse)?,
            size_bytes: size_bytes.ok_or_else(|| de::Error::missing_field("size_bytes"))?,
            kind: kind.ok_or_else(|| de::Error::missing_field("kind"))?,
            name: checked(name, "name", SafeName::parse)?,
        })
    }
}

impl<'de> Deserialize<'de> for PromptAttachment {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        d.deserialize_map(PromptAttachmentVisitor)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StagedAttachment {
    pub attachment: PromptAttachment,
    pub path: StagedPath,
}
