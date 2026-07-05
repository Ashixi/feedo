fn main() -> Result<(), Box<dyn std::error::Error>> {
    tonic_build::compile_protos("proto/consensus.proto")?;
    tonic_build::compile_protos("proto/storage.proto")?;
    tonic_build::compile_protos("proto/feedo.proto")?;
    tonic_build::compile_protos("proto/farcaster.proto")?;

    Ok(())
}
