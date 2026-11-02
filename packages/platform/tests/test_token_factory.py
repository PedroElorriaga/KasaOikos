"""Verificação da fábrica de tokens de teste (tarefa 4.1)."""

import httpx
import jwt
import pytest

from hm_platform.testing.tokens import AUDIENCE, ISSUER, JWKS_URL, FakeJWKS, TokenFactory


async def public_key_for(token: str, jwks: FakeJWKS) -> object:
    async with httpx.AsyncClient(transport=jwks.transport()) as http:
        document = (await http.get(JWKS_URL)).json()
    kid = jwt.get_unverified_header(token)["kid"]
    [jwk] = [k for k in document["keys"] if k["kid"] == kid]
    return jwt.PyJWK(jwk).key


def decode(token: str, key: object) -> dict[str, object]:
    return jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER)  # type: ignore[arg-type]


async def test_valid_token_decodes_with_published_public_key(
    token_factory: TokenFactory, fake_jwks: FakeJWKS
) -> None:
    token = token_factory.valid(sub="user-1")

    claims = decode(token, await public_key_for(token, fake_jwks))

    assert claims["sub"] == "user-1"
    assert claims["email"] == "ana@example.com"
    assert claims["name"] == "Ana Souza"
    assert jwt.get_unverified_header(token) == {"alg": "RS256", "kid": "test-key-1", "typ": "JWT"}
    assert fake_jwks.fetches == 1


@pytest.mark.parametrize(
    ("variant", "error"),
    [
        ("expired", jwt.ExpiredSignatureError),
        ("wrong_issuer", jwt.InvalidIssuerError),
        ("wrong_audience", jwt.InvalidAudienceError),
        ("bad_signature", jwt.InvalidSignatureError),
    ],
)
async def test_broken_variants_fail_for_the_expected_reason(
    token_factory: TokenFactory, fake_jwks: FakeJWKS, variant: str, error: type[Exception]
) -> None:
    token = getattr(token_factory, variant)()
    with pytest.raises(error):
        decode(token, await public_key_for(token, fake_jwks))


def test_unknown_kid_is_not_published(token_factory: TokenFactory, fake_jwks: FakeJWKS) -> None:
    token = token_factory.unknown_kid()
    kid = jwt.get_unverified_header(token)["kid"]
    assert kid not in {k["kid"] for k in fake_jwks.document()["keys"]}


async def test_jwks_answers_only_its_url(fake_jwks: FakeJWKS) -> None:
    async with httpx.AsyncClient(transport=fake_jwks.transport()) as http:
        assert (await http.get("http://keycloak.test/other")).status_code == 404
    assert fake_jwks.fetches == 0
