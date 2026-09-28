pub fn fixture() -> String {
    let mut integer = itoa::Buffer::new();
    let mut float = ryu::Buffer::new();
    format!("{}:{}", integer.format(42), float.format(1.5))
}

#[cfg(test)]
mod tests {
    #[test]
    fn cached_formatters_link() {
        assert_eq!(super::fixture(), "42:1.5");
    }
}
