from app.verifier_providers.contracts import ProviderResponse

print("FIELDS:")
for name, field in ProviderResponse.model_fields.items():
    print(f"{name} -> {field.annotation}")