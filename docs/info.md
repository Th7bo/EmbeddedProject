
---

# Snakes and Ladders

## Hardware

- **Board:** a 4×4 grid of NFC tags (16 squares). The squares are unmarked. Snakes and ladders exist only in software and are shown on the screen.
- **Meeples (one per player):** an ESP-01 with a PN532 NFC reader (I2C), an LED and its own battery (LiPo + 3.3 V regulator). Each meeple reads the tag it's standing on and sends it to the ESP32 over MQTT.
- **Game master (ESP32):** a 128×64 graphic LCD, one push button and a buzzer. It runs the game and decides everything.

## Reset

Holding the push button for about 3 seconds resets the game at any time. This gives the same state as when the ESP32 starts up.

## Screen

- **At startup:** shows the connected players and the setup instructions (choose the start corner, then the density).
- **During the game:** the left half shows each player, their current square and the last roll, with a marker for whose turn it is. The right half shows the 4×4 board in the same rotation as the physical board: ladders as solid lines, snakes as dotted lines, and a dot for each meeple.

## Setup

1. **Start corner:** a random meeple starts flashing. That player places it on one of the four corners. That corner becomes square 1, and the numbering goes **to the left** along the edge, then zig-zags back row by row up to square 16.
    
2. **Density:** the players choose how many snakes and ladders they want on the LCD. A short press cycles through the options and a double press confirms.

| Density | Snakes + ladders |
| --- | --- |
| Low | 2 |
| Medium | 3–4 |
| High | 5–6 |

3. **Generation:** the snakes and ladders are generated randomly with these rules:
    
    - There's no snake or ladder on square 1 or square 16, and no ladder leads to 16.
    - Every snake or ladder moves at least one row (4 squares).
    - No square is used by more than one snake or ladder.
    - There's always at least one snake and one ladder.

## Gameplay

1. The players press the button to start the game. A random player goes first.
2. **Check-in:** when it's a player's turn, their meeple's LED blinks. Players can share a square, so the blinking LED shows whose turn it is. The player places their meeple on its current square to check in.
3. **Roll:** after checking in, the player presses the button to roll a **d4 (1–4)**. A d4 is used because a d6 would end a 4×4 game too quickly.
4. **Move:** the player walks their meeple along the path. The buzzer beeps faster the fewer steps they are from their target square. When they reach it, a confirmation sound plays.
5. **Snakes and ladders:** if the square has a ladder, a victory sound plays. If it has a snake, a losing sound plays. The player then **walks the path** to the other end, up or down, with the buzzer guiding them the same way.
6. The game doesn't move to the next player until the meeple is on the correct square.

## Winning

You have to land **exactly** on square 16. If you overshoot, you move backwards by the extra steps. For example, from square 14 a roll of 4 takes you to 16 and then back 2, to square 14. After bouncing back, the square you land on is still checked for a snake or ladder.

The first player to land exactly on square 16 wins.

---