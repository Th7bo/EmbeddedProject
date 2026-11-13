// Hardware smoke test for the control base: LCD, button, buzzer, LED.
// Press the button -> short beep and the LED toggles.
#include <Arduino.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "pins.h"

LiquidCrystal_I2C lcd(LCD_ADDR, LCD_COLS, LCD_ROWS);

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);

  Wire.begin(PIN_SDA, PIN_SCL);
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("S&L base");
  lcd.setCursor(0, 1);
  lcd.print("press button");
}

void loop() {
  static bool led = false;
  static bool lastPressed = false;

  bool pressed = digitalRead(PIN_BUTTON) == LOW;
  if (pressed && !lastPressed) {
    led = !led;
    digitalWrite(PIN_LED, led);
    tone(PIN_BUZZER, 2000, 80);
    lcd.setCursor(0, 1);
    lcd.print(led ? "LED on      " : "LED off     ");
    Serial.println("button");
  }
  lastPressed = pressed;
  delay(20);  // crude debounce
}
