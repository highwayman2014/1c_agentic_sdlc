//! Offline SQLite -> shared baseline migration. No embedder or source indexer is constructed.
use bsl_search::{CorpusId, ExternalBaselineAdapter, ExternalBaselineConfig, IndexedDocument,
    Snapshot, SnapshotPublishMetadata, SnapshotPublisher, fingerprint_indexed_documents,
    semantic_key_for_indexed_document};
use rusqlite::{Connection, OpenFlags};
use std::{env, fs, error::Error};

fn run() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 { return Err("usage: bsl_baseline_import SQLITE SNAPSHOT PRIVATE_PG_ENV".into()); }
    let secret = fs::read_to_string(&args[3])?;
    let password = secret.lines().find_map(|s| s.strip_prefix("POSTGRES_PASSWORD=")).ok_or("missing password")?;
    // This utility writes only the new local PostgreSQL service. Original SQLite includes WAL.
    let db = Connection::open_with_flags(&args[1], OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    db.execute_batch("PRAGMA query_only=ON; BEGIN;")?;
    let generation: String = db.query_row("SELECT value FROM meta WHERE key='embedding_generation'", [], |r| r.get(0))?;
    let version: i64 = db.query_row("PRAGMA user_version", [], |r| r.get(0))?;
    let sidecar: serde_json::Value = serde_json::from_str(&fs::read_to_string(format!("{}.usearch.json",args[1]))?)?;
    let model=sidecar["model_id"].as_str().ok_or("missing model")?;
    let dim=sidecar["dim"].as_u64().ok_or("missing dimension")? as usize;
    if sidecar["generation"].as_u64().map(|n|n.to_string()) != Some(generation.clone()) || version != 1 || sidecar["embed_text_version"] != 1 {
        return Err("SQLite / sidecar identity mismatch".into());
    }
    let config=ExternalBaselineConfig::postgres(format!("host=127.0.0.1 port=15432 dbname=bsl_baseline user=bsl_admin password={password}")).with_schema("smm_auto");
    let adapter=ExternalBaselineAdapter::new(config)?;
    adapter.migrate_storage()?;
    adapter.ensure_embedding_identity(model,dim)?;
    let mut statement=db.prepare("SELECT f.collection,f.root_id,f.path,c.symbol_name,c.kind,c.line_start,c.line_end,c.text,c.graph_context,c.embedding FROM chunks c JOIN files f ON f.id=c.file_id WHERE f.collection='code' ORDER BY f.root_id,f.path,c.line_start,c.id")?;
    let mut rows=statement.query([])?;
    let mut documents=Vec::new();
    let mut vectors=Vec::new();
    let mut stored=0usize;
    let mut first_vector=None;
    while let Some(row)=rows.next()? {
        let text:String=row.get(7)?;
        let document=IndexedDocument{collection:row.get(0)?,root_id:row.get(1)?,path:row.get(2)?,symbol_name:row.get(3)?,kind:row.get(4)?,line_start:row.get::<_,i64>(5)? as u32,line_end:row.get::<_,i64>(6)? as u32,content_hash:blake3::hash(text.as_bytes()).to_hex().to_string(),text,graph_context:row.get(8)?,source_span:None};
        let blob:Vec<u8>=row.get(9)?;
        if blob.len()!=dim*4 {return Err("vector dimension mismatch".into());}
        let vector:Vec<f32>=blob.chunks_exact(4).map(|b|f32::from_le_bytes(b.try_into().unwrap())).collect();
        if vector.iter().any(|f| !f.is_finite()) {return Err("non-finite vector".into());}
        if first_vector.is_none(){first_vector=Some(vector.clone());}
        vectors.push((semantic_key_for_indexed_document(&document),vector));
        documents.push(document);
        if vectors.len()==256 {
            adapter.store_embeddings(model,dim,&vectors)?;stored+=vectors.len();vectors.clear();
            if stored%8192==0 {println!("Existing vectors transferred: {stored}");}
        }
    }
    if !vectors.is_empty(){adapter.store_embeddings(model,dim,&vectors)?;stored+=vectors.len();}
    let expected=sidecar["count"].as_u64().ok_or("missing vector count")? as usize;
    if stored!=expected {return Err("source coverage differs from saved sidecar".into());}
    let fingerprint=fingerprint_indexed_documents(&documents);
    let snapshot=Snapshot::new(&args[2],CorpusId::WorkspaceCode).with_fingerprint(&fingerprint);
    // The historic Git SHA is unknown: do not label this data as the current main commit.
    let existing=adapter.snapshot_details(&args[2])?;
    if let Some(ref saved)=existing {
        if saved.snapshot.fingerprint.as_deref()!=Some(fingerprint.as_str()) || saved.snapshot.documents!=documents.len() {
            return Err("refusing to replace a different published snapshot".into());
        }
        println!("Matching snapshot retained: chunks={}, fingerprint={fingerprint}",documents.len());
    } else {
        let report=adapter.publish_snapshot(&snapshot,&SnapshotPublishMetadata{branch:Some("legacy-sqlite".into()),commit:None},&documents)?;
        println!("Snapshot written: files={}, chunks={}, fingerprint={fingerprint}",report.written_files,documents.len());
    }
    let complete=existing.as_ref().and_then(|s|s.semantic_publication.as_ref())
        .is_some_and(|s|s.complete && s.model_id==model && s.dimension==dim);
    let served=if complete {documents.len()} else {adapter.populate_serving_semantic(&args[2],model,dim)?};
    if served!=documents.len(){return Err("semantic serving coverage incomplete".into());}
    let hits=adapter.lexical_search_baseline(&args[2],"ЗагрузитьСписаниеЗапасовСМЗ",Some("code"),3)?;
    if hits.is_empty(){return Err("lexical acceptance query returned no hits".into());}
    let hits=adapter.semantic_search_baseline(&args[2],&first_vector.ok_or("empty index")?,model,dim,Some("code"),3)?;
    if hits.is_empty(){return Err("saved-vector semantic query returned no hits".into());}
    println!("Verified snapshot: chunks={served}, model={model}, dim={dim}, source_generation={generation}; provider requests=0");
    Ok(())
}
fn main(){if run().is_err(){eprintln!("Baseline import failed; no credentials printed. Inspect the local service and source identity.");std::process::exit(1);}}
