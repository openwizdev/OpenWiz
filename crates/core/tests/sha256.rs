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

mod previous {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];

    const H0: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];

    fn compress(h: &mut [u32; 8], block: &[u8; 64]) {
        let mut w = [0u32; 64];
        let (words, _) = block.as_chunks::<4>();
        for (i, word) in words.iter().enumerate() {
            w[i] = u32::from_be_bytes(*word);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh] = *h;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (state, add) in h.iter_mut().zip([a, b, c, d, e, f, g, hh]) {
            *state = state.wrapping_add(add);
        }
    }

    pub struct Hasher {
        state: [u32; 8],
        block: [u8; 64],
        filled: usize,
        len: u64,
    }

    impl Hasher {
        pub fn new() -> Self {
            Self {
                state: H0,
                block: [0; 64],
                filled: 0,
                len: 0,
            }
        }

        pub fn update(&mut self, mut data: &[u8]) {
            self.len = self.len.wrapping_add(data.len() as u64);
            while !data.is_empty() {
                let take = data.len().min(64 - self.filled);
                self.block[self.filled..self.filled + take].copy_from_slice(&data[..take]);
                self.filled += take;
                data = &data[take..];
                if self.filled == 64 {
                    compress(&mut self.state, &self.block);
                    self.filled = 0;
                }
            }
        }

        pub fn finish(mut self) -> String {
            let bit_len = self.len.wrapping_mul(8);
            let zeros = (55usize.wrapping_sub(self.filled)) % 64;
            let mut tail = vec![0x80];
            tail.resize(1 + zeros, 0);
            tail.extend_from_slice(&bit_len.to_be_bytes());
            self.update(&tail);
            self.state
                .iter()
                .map(|word| format!("{word:08x}"))
                .collect()
        }
    }

    pub fn sha256_hex(data: &[u8]) -> String {
        let mut hasher = Hasher::new();
        hasher.update(data);
        hasher.finish()
    }
}

#[test]
fn sha256_matches_the_previous_hasher_on_every_cut() {
    let data: Vec<u8> = (0..2048u32).map(|i| (i.wrapping_mul(17)) as u8).collect();
    for len in (0..=128).chain([200, 255, 256, 1000, 2048]) {
        assert_eq!(
            sha256_hex(&data[..len]),
            previous::sha256_hex(&data[..len]),
            "{len}"
        );
        for cut in [0, 1, 55, 56, 63, 64, len / 2, len] {
            if cut > len {
                continue;
            }
            let mut old = previous::Hasher::new();
            old.update(&data[..cut]);
            old.update(&data[cut..len]);
            let mut new = Sha256Hasher::new();
            new.update(&data[..cut]);
            new.update(&data[cut..len]);
            assert_eq!(new.finish(), old.finish(), "{len} cut at {cut}");
        }
    }
}
