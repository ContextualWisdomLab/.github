# Security

- Pin the shared Strix CI runtime to PyJWT 2.15.1. This retains the 2.15.0
  security correction that converts malicious deeply nested JWT payload
  recursion into a bounded `DecodeError`, while also carrying the signed
  2.15.1 Base64URL-padding correction. The source input and generated hash
  lock now carry the same exact release.
