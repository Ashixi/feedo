use std::io::Result;
fn main() -> Result<()> {
    let mut config = prost_build::Config::new();
    config.type_attribute(".", "#[derive(serde::Serialize, serde::Deserialize)]");
    config.compile_protos(&["./proto/feedo.proto"], &["./proto"])?;
    
    #[cfg(feature = "farcaster")]
    {
        tonic_build::configure()
            .build_server(true)
            .build_client(false)
            .compile(&["./proto/farcaster.proto"], &["./proto"])?;
    }
    
    Ok(())
}
