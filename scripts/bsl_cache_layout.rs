//! Read-only derived-cache layout helper for the validated bsl-analyzer 0.4.3 recipe.
//! Build against matching project_model/blake3 libraries; never start MCP or an indexer.
use std::{env, error::Error, path::Path};
fn field(h: &mut blake3::Hasher, bytes: &[u8]) {
    h.update(&(bytes.len() as u64).to_le_bytes()); h.update(bytes);
}
fn run() -> Result<(), Box<dyn Error>> {
    let a: Vec<String> = env::args().collect();
    if a.len() != 3 { return Err("usage: bsl-cache-layout WORKSPACE CACHE_BASE".into()); }
    let project = project_model::Project::new(Path::new(&a[1]))?;
    if project.source_exclusions().declared().count() != 0 {
        return Err("layout helper does not support declared source exclusions; do not guess a namespace".into());
    }
    let root = project.root.canonicalize()?;
    let mut h = blake3::Hasher::new(); h.update(b"bsl-analyzer/workspace-derived-cache/v1");
    field(&mut h, root.as_os_str().as_encoded_bytes());
    field(&mut h, project.extension_topology().fingerprint().as_bytes());
    println!("{}", Path::new(&a[2]).join("workspaces/v1").join(h.finalize().to_hex().as_str()).display());
    Ok(())
}
fn main() { if let Err(e) = run() { eprintln!("{e}"); std::process::exit(1); } }
