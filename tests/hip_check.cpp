// Copyright Advanced Micro Devices, Inc.
// SPDX-License-Identifier: MIT

#include <cstdio>
#include <cstdlib>
#include <hip/hip_runtime.h>

// Device visibility is the usual cause of a zero-device runtime on a CI runner,
// so report it alongside any failure.
static void report_environment() {
  int device_count = -1;
  hipError_t err = hipGetDeviceCount(&device_count);
  fprintf(stderr, "hip_check: visible devices: %d (hipGetDeviceCount: %s)\n",
          device_count, hipGetErrorName(err));
  for (const char *name : {"ROCR_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES",
                           "CUDA_VISIBLE_DEVICES", "GPU_DEVICE_ORDINAL"}) {
    const char *value = getenv(name);
    fprintf(stderr, "hip_check: %s=%s\n", name, value ? value : "<unset>");
  }
}

static void check_hip_error(hipError_t err, const char *api) {
  if (err == hipSuccess)
    return;
  fprintf(stderr, "hip_check: %s failed: %s (%s)\n", api, hipGetErrorName(err),
          hipGetErrorString(err));
  exit(1);
}

#define HIP_CHECK(expr) check_hip_error((expr), #expr)

__global__ void squares(int *buf) {
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  printf("Thread %#04x is writing %4d\n", i, i * i);
  buf[i] = i * i;
}
int main() {
  constexpr int gridsize = 1;
  constexpr int blocksize = 64;
  constexpr int size = gridsize * blocksize;
  report_environment();
  int *d_buf = nullptr;
  HIP_CHECK(hipHostMalloc(&d_buf, size * sizeof(int)));
  hipLaunchKernelGGL(squares, gridsize, blocksize, 0, 0, d_buf);
  HIP_CHECK(hipGetLastError());
  HIP_CHECK(hipDeviceSynchronize());

  // Check results.
  int mismatches_count = 0;
  for (int i = 0; i < size; ++i) {
    int square = i * i;
    if (d_buf[i] != square) {
      fprintf(stderr,
              "Element at index %d expected value %d, actual value: %d\n", i,
              square, d_buf[i]);
      ++mismatches_count;
    }
  }
  if (mismatches_count > 0) {
    fprintf(stderr, "There were %d mismatches\n", mismatches_count);
    return 1;
  }

  return 0;
}
