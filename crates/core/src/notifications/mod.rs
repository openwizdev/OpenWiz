//! Transport-independent notification interfaces (0.0.15 T1).
//! No scheduler, provider, subscription creation or work effects.
//! T3 adds policy/grouping; T6 adds stock, each in its own module.
pub mod boundary;
pub mod grouping;
pub mod model;
pub mod policy;
pub mod stock;
