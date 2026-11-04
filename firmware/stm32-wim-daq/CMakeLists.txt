cmake_minimum_required(VERSION 3.22)

# Usage (see README.md):
#   cmake -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/arm-gcc-toolchain.cmake -DCMAKE_BUILD_TYPE=Release
#   cmake --build build
# Options: -DKIFARU_RIG=ON (lab rig geometry), -DWITH_LWIP=ON (UDP transport; needs CubeMX-generated LWIP/ folder)

project(kifaru_wim_daq C ASM)
set(CMAKE_C_STANDARD 11)

option(KIFARU_RIG "Build for the 1:10 laboratory rig geometry" OFF)
option(WITH_LWIP  "Enable Ethernet/UDP transport (requires CubeMX LwIP middleware in ${CMAKE_SOURCE_DIR}/LWIP)" OFF)

# --- external dependencies (fetched as git submodules or copied; paths overridable) ----------------------------
set(STM32_HAL_DIR   ${CMAKE_SOURCE_DIR}/third_party/STM32CubeH7/Drivers/STM32H7xx_HAL_Driver CACHE PATH "STM32H7 HAL")
set(CMSIS_DEV_DIR   ${CMAKE_SOURCE_DIR}/third_party/STM32CubeH7/Drivers/CMSIS/Device/ST/STM32H7xx CACHE PATH "CMSIS device")
set(CMSIS_CORE_DIR  ${CMAKE_SOURCE_DIR}/third_party/STM32CubeH7/Drivers/CMSIS/Include CACHE PATH "CMSIS core")
set(FREERTOS_DIR    ${CMAKE_SOURCE_DIR}/third_party/FreeRTOS-Kernel CACHE PATH "FreeRTOS kernel")

file(GLOB HAL_SRC ${STM32_HAL_DIR}/Src/stm32h7xx_hal*.c)
list(FILTER HAL_SRC EXCLUDE REGEX ".*_template\\.c$")

set(FREERTOS_SRC
    ${FREERTOS_DIR}/tasks.c ${FREERTOS_DIR}/queue.c ${FREERTOS_DIR}/list.c ${FREERTOS_DIR}/timers.c
    ${FREERTOS_DIR}/event_groups.c ${FREERTOS_DIR}/stream_buffer.c
    ${FREERTOS_DIR}/portable/MemMang/heap_4.c
    ${FREERTOS_DIR}/portable/GCC/ARM_CM7/r0p1/port.c)

set(APP_SRC
    Core/Src/main.c
    Core/Src/stm32h7xx_it.c
    Core/Src/system_stm32h7xx.c          # copy from CMSIS device templates (Source/Templates/system_stm32h7xx.c)
    Core/Src/startup_stm32h743xx.s       # copy from CMSIS device templates (Source/Templates/gcc/startup_stm32h743xx.s)
    App/wim_dsp.c App/frames.c App/timebase.c
    App/acq_task.c App/detect_task.c App/health_task.c App/comms_task.c
    Drivers/ads131m08.c Drivers/loop_detector.c Drivers/ir_beam.c)

add_executable(${PROJECT_NAME}.elf ${APP_SRC} ${HAL_SRC} ${FREERTOS_SRC})

target_include_directories(${PROJECT_NAME}.elf PRIVATE
    Core/Inc App Drivers
    ${STM32_HAL_DIR}/Inc ${STM32_HAL_DIR}/Inc/Legacy
    ${CMSIS_DEV_DIR}/Include ${CMSIS_CORE_DIR}
    ${FREERTOS_DIR}/include ${FREERTOS_DIR}/portable/GCC/ARM_CM7/r0p1)

target_compile_definitions(${PROJECT_NAME}.elf PRIVATE
    STM32H743xx USE_HAL_DRIVER HSE_VALUE=8000000U
    $<$<BOOL:${KIFARU_RIG}>:KIFARU_RIG=1>
    $<$<BOOL:${WITH_LWIP}>:WITH_LWIP=1>)

target_compile_options(${PROJECT_NAME}.elf PRIVATE
    -mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard
    -ffunction-sections -fdata-sections -fno-common -fstack-usage
    -Wall -Wextra -Wdouble-promotion -Wno-unused-parameter
    $<$<CONFIG:Debug>:-Og -g3>
    $<$<CONFIG:Release>:-O2 -g>)

target_link_options(${PROJECT_NAME}.elf PRIVATE
    -mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard
    -T${CMAKE_SOURCE_DIR}/STM32H743ZITX_FLASH.ld
    -Wl,--gc-sections -Wl,-Map=${PROJECT_NAME}.map -Wl,--print-memory-usage
    --specs=nano.specs --specs=nosys.specs -u _printf_float)

if(WITH_LWIP)
    file(GLOB_RECURSE LWIP_SRC ${CMAKE_SOURCE_DIR}/LWIP/*.c ${CMAKE_SOURCE_DIR}/Middlewares/Third_Party/LwIP/src/core/*.c
         ${CMAKE_SOURCE_DIR}/Middlewares/Third_Party/LwIP/src/core/ipv4/*.c ${CMAKE_SOURCE_DIR}/Middlewares/Third_Party/LwIP/src/api/*.c
         ${CMAKE_SOURCE_DIR}/Middlewares/Third_Party/LwIP/src/netif/ethernet.c ${CMAKE_SOURCE_DIR}/Middlewares/Third_Party/LwIP/system/OS/sys_arch.c)
    target_sources(${PROJECT_NAME}.elf PRIVATE ${LWIP_SRC})
    target_include_directories(${PROJECT_NAME}.elf PRIVATE LWIP/App LWIP/Target Middlewares/Third_Party/LwIP/src/include Middlewares/Third_Party/LwIP/system)
endif()

add_custom_command(TARGET ${PROJECT_NAME}.elf POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O ihex   $<TARGET_FILE:${PROJECT_NAME}.elf> ${PROJECT_NAME}.hex
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:${PROJECT_NAME}.elf> ${PROJECT_NAME}.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:${PROJECT_NAME}.elf>)
