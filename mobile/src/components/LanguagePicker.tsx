import { useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { useLanguage, type Language } from "@/lib/i18n";

const options: { value: Language; label: string }[] = [
  { value: "en", label: "English" },
  { value: "hi", label: "हिंदी" },
  { value: "mr", label: "मराठी" },
];

export function LanguagePicker() {
  const { language, setLanguage } = useLanguage();
  const [open, setOpen] = useState(false);
  const current = options.find((item) => item.value === language) ?? options[0];

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Choose language"
        onPress={() => setOpen(true)}
        style={styles.trigger}
      >
        <Text style={styles.triggerText}>{current.label} ▾</Text>
      </Pressable>

      <Modal
        visible={open}
        transparent
        animationType="fade"
        onRequestClose={() => setOpen(false)}
      >
        <Pressable style={styles.overlay} onPress={() => setOpen(false)}>
          <View style={styles.menu}>
            <Text style={styles.heading}>Choose language / भाषा चुनें</Text>
            {options.map((item) => (
              <Pressable
                key={item.value}
                accessibilityRole="button"
                accessibilityState={{ selected: language === item.value }}
                onPress={() => {
                  setOpen(false);
                  void setLanguage(item.value);
                }}
                style={[
                  styles.option,
                  language === item.value && styles.selected,
                ]}
              >
                <Text style={styles.optionText}>{item.label}</Text>
                {language === item.value ? (
                  <Text style={styles.check}>✓</Text>
                ) : null}
              </Pressable>
            ))}
          </View>
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  trigger: {
    alignSelf: "flex-start",
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  triggerText: {
    color: "#222222",
    fontSize: 14,
  },
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0, 0, 0, 0.35)",
    justifyContent: "center",
    padding: 20,
  },
  menu: {
    backgroundColor: "#FFFFFF",
    borderRadius: 16,
    padding: 12,
  },
  heading: {
    color: "#222222",
    fontSize: 17,
    fontWeight: "600",
    marginBottom: 8,
  },
  option: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: 12,
    borderRadius: 10,
  },
  selected: {
    backgroundColor: "#EEEEEE",
  },
  optionText: {
    color: "#222222",
    fontSize: 16,
  },
  check: {
    color: "#222222",
    fontWeight: "700",
  },
});
