//! Verify actual project configuration and reader permissions without starting MCP or an embedder.
use bsl_search::{ExternalBaselineAdapter,ExternalBaselineConfig};
use rusqlite::{Connection,OpenFlags};
use std::{env,error::Error};

fn verify()->Result<(),Box<dyn Error>> {
    let args:Vec<String>=env::args().collect();
    if args.len()!=3{return Err("usage: bsl_baseline_verify WORKSPACE SAVED_SQLITE".into());}
    let project=project_model::Project::new(&args[1])?;
    let baseline=&project.config.search.baseline;
    let resolved=project_model::resolve_postgres_url(&baseline.postgres,project_model::PostgresAccessMode::Reader)?;
    let adapter=ExternalBaselineAdapter::new(ExternalBaselineConfig::postgres(resolved.url).with_schema(baseline.postgres.schema.as_deref().ok_or("missing schema")?))?;
    adapter.check_storage_readiness()?;
    let snapshot=baseline.workspace_code.snapshot_id.as_deref().ok_or("snapshot must be explicit")?;
    let details=adapter.snapshot_details(snapshot)?.ok_or("snapshot missing")?;
    let model=baseline.embedding.model.as_deref().ok_or("missing model")?;
    let dim=baseline.embedding.dimension.ok_or("missing dimension")?;
    if adapter.read_embedding_identity()?!=Some((model.to_owned(),dim)){return Err("model mismatch".into());}
    let coverage=adapter.embedding_coverage(Some(model),Some(dim))?;
    if coverage.is_empty() || coverage.iter().any(|c|c.active_payloads!=c.covered_payloads){return Err("incomplete baseline coverage".into());}
    let lexical=adapter.lexical_search_baseline(snapshot,"ЗагрузитьСписаниеЗапасовСМЗ",Some("code"),3)?;
    if lexical.is_empty(){return Err("no lexical hits".into());}
    let sqlite=Connection::open_with_flags(&args[2],OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let blob:Vec<u8>=sqlite.query_row("SELECT embedding FROM chunks WHERE embedding IS NOT NULL LIMIT 1",[],|r|r.get(0))?;
    let vector:Vec<f32>=blob.chunks_exact(4).map(|b|f32::from_le_bytes(b.try_into().unwrap())).collect();
    if vector.len()!=dim{return Err("dimension mismatch".into());}
    let hits=adapter.semantic_search_baseline(snapshot,&vector,model,dim,Some("code"),3)?;
    if hits.is_empty(){return Err("no semantic hits".into());}
    println!("Reader verified: workspace={}, snapshot={}, lexical_hits={}, semantic_hits={}, coverage={:?}, details={:?}; embedding provider requests=0",project.root.display(),snapshot,lexical.len(),hits.len(),coverage,details);
    Ok(())
}
fn main(){if let Err(error)=verify(){
    let mut message=error.to_string();
    // The connection helper is private. Never echo a reader password from an error.
    if let Ok(text)=std::fs::read_to_string("D:/tools/bsl-baseline/reader.json") {
        if let Ok(value)=serde_json::from_str::<serde_json::Value>(&text) {
            if let Some(password)=value["password"].as_str(){message=message.replace(password,"[redacted]");}
        }
    }
    eprintln!("Baseline reader verification failed: {message}");std::process::exit(1);
}}
