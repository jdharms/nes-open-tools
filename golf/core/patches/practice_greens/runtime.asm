; Standalone practice hack. Bank 2's former UK terrain, not shared patch space.
.org $8400
RoundInit:
    sta $04FD
    sta $04FE
    ldx #0
@draw:
    jsr $D29C
    and #$7F
    cmp #GREEN_COUNT
    bcs @draw
    sta $26
    txa
    tay
@check:
    dey
    bmi @accept
    lda $7100,y
    cmp $26
    beq @draw
    bne @check
@accept:
    lda $26
    sta $7100,x
    tay
    lda BANK_TABLE,y
    sta $7112,x
    lda LO_TABLE,y
    sta $7124,x
    lda HI_TABLE,y
    sta $7136,x
@pin:
    jsr $D29C
    and #$1F
    cmp PIN_COUNT_TABLE,y
    bcs @pin
    sta $714B,x
    inx
    cpx #18
    bne @draw
    rts

SetupGreen:
    txa
    pha
    ldx $94
    lda $7124,x
    sta $50
    lda $7136,x
    sta $51
    lda $7112,x
    sta $714A
    lda $714B,x
    sta $26
    lda $7100,x
    tax
    lda PIN_LO_TABLE,x
    sta $28
    lda PIN_HI_TABLE,x
    sta $29
    lda $26
    asl a
    tay
    lda ($28),y
    sta $7148
    iny
    lda ($28),y
    sta $7149
    pla
    tax
    rts

PlaceBall:
    lda $A5
    lsr a
    lsr a
    lsr a
    sta $2C
    lda $A6
    lsr a
    lsr a
    lsr a
    sta $2D
    lda #$FF
    sta $2A
@retry:
    jsr $D29C
    and #$1F
    cmp #24
    bcs @reject
    sta $26
    jsr $D29C
    and #$1F
    cmp #24
    bcs @reject
    sta $27
    jsr ValidTile
    bcs @found
@reject:
    dec $2A
    bne @retry
    ; Deterministic scan guarantees a valid fallback; no off-green escape.
    lda #0
    sta $26
    sta $27
@scan:
    jsr ValidTile
    bcs @found
    inc $26
    lda $26
    cmp #24
    bcc @scan
    lda #0
    sta $26
    inc $27
    jmp @scan
@found:
    lda $26
    clc
    adc $A3
    sta $0115,x
    lda $27
    clc
    adc $A4
    sta $0119,x
    lda #0
    adc #0
    sta $011B,x
    jsr $D29C
    and #$E0
    ora #$10
    sta $0113,x
    jsr $D29C
    and #$E0
    ora #$10
    sta $0117,x
    lda #2
    sta $0111,x
    rts

ValidTile:
    lda $26
    cmp $2C
    bne @pointer
    lda $27
    cmp $2D
    beq @no
@pointer:
    lda $27
    asl a
    asl a
    asl a
    sta $28
    lda #$75
    sta $29
    lda $28
    asl a
    bcc @add8
    inc $29
@add8:
    clc
    adc $28
    bcc @addx
    inc $29
@addx:
    clc
    adc $26
    bcc @base
    inc $29
@base:
    clc
    adc #$A6
    bcc @read
    inc $29
@read:
    sta $28
    ldy #0
    lda ($28),y
    cmp #$30
    bcc @no
    cmp #$48
    bcc @yes
    cmp #$88
    bcc @no
    cmp #$A8
    bcc @yes
    cmp #$B0
    bne @no
@yes:
    sec
    rts
@no:
    clc
    rts

StopBall:
    lda #2
    sta $05B0
    sta $D2
    lda $05B9
    bne @done
    jsr $EDBC
    lda $C9
    cmp #6
    beq @done
    ldx $99
    lda #5
    sta $011F,x
    lda #$FF
    sta $05B9
@done:
    rts
