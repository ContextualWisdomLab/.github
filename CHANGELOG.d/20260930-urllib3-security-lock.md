# Security

- Pin the shared pip-audit and Strix CI runtimes to urllib3 2.8.0, which fixes
  the HTTPS-proxy TLS-policy crossover and two streaming denial-of-service
  vulnerabilities present in 2.7.0. Both source inputs and generated hash locks
  now carry the same exact version.
