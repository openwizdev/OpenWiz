//! The streaming SHA-256 (`Sha256Hasher`) that staging hashes with: the
//! same hash as `sha256_hex` of the whole input, however the bytes are cut
//! into pieces, and the FIPS 180-4 examples.

use openwiz_core::messaging::{Sha256Hasher, sha256_hex};

fn streamed(pieces: &[&[u8]]) -> String {
    let mut hasher = Sha256Hasher::new();
    for piece in pieces {
        hasher.update(piece);
    }
    hasher.finish()
}

#[test]
fn sha256_stream_contracts_preserve_original_cases() {
    let cases: [(&str, fn()); 3] = [
        (
            "every_cut_gives_the_whole_inputs_hash",
            every_cut_gives_the_whole_inputs_hash,
        ),
        ("the_fips_examples", the_fips_examples),
        (
            "the_single_block_padding_boundary",
            the_single_block_padding_boundary,
        ),
    ];
    for (name, proof) in cases {
        eprintln!("TA2 case: sha256_stream::{name}");
        proof();
    }
}

fn the_fips_examples() {
    for (input, hex) in [
        (
            &b""[..],
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ),
        (
            b"abc",
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        ),
        (
            b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
        ),
    ] {
        assert_eq!(streamed(&[input]), hex);
        assert_eq!(sha256_hex(input), hex);
    }
    let million = vec![b'a'; 1_000_000];
    let hex = "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0";
    assert_eq!(sha256_hex(&million), hex);
    let pieces: Vec<&[u8]> = million.chunks(997).collect();
    assert_eq!(streamed(&pieces), hex);
}

fn the_single_block_padding_boundary() {
    // Independent digests (Python `hashlib`, FIPS 180-4) for `b'a' * n`
    // around the one-block padding boundary: exactly 55 bytes is the largest
    // input whose 0x80 and length still fit one block (55 + 1 + 8 = 64), so a
    // wrong zero count there never reaches `every_cut_gives_the_whole_inputs_hash`,
    // which compares the hasher only with itself.
    for (n, hex) in [
        (
            55usize,
            "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318",
        ),
        (
            63,
            "7d3e74a05d7db15bce4ad9ec0658ea98e3f06eeecf16b4c6fff2da457ddc2f34",
        ),
        (
            64,
            "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb",
        ),
        (
            65,
            "635361c48bb9eab14198e76ea8ab7f1a41685d6ad62aa9146d301d4f17eb0ae0",
        ),
    ] {
        let data = vec![b'a'; n];
        assert_eq!(sha256_hex(&data), hex, "{n} whole via sha256_hex");
        assert_eq!(streamed(&[&data]), hex, "{n} whole via Sha256Hasher");
        let bytes: Vec<&[u8]> = data.chunks(1).collect();
        assert_eq!(streamed(&bytes), hex, "{n} a byte at a time");
    }
}

fn every_cut_gives_the_whole_inputs_hash() {
    let data: Vec<u8> = (0..300u32).map(|i| (i * 31 % 251) as u8).collect();
    for len in 0..data.len() {
        let whole = sha256_hex(&data[..len]);
        assert_eq!(streamed(&[&data[..len]]), whole, "{len}");
        for cut in 0..=len {
            assert_eq!(
                streamed(&[&data[..cut], &data[cut..len]]),
                whole,
                "{len} cut at {cut}"
            );
        }
        let bytes: Vec<&[u8]> = data[..len].chunks(1).collect();
        assert_eq!(streamed(&bytes), whole, "{len} a byte at a time");
    }
    assert_eq!(Sha256Hasher::default().finish(), sha256_hex(b""));
}
