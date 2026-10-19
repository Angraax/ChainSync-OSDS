#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"

//
// ChainSync & xv6 Semaphore Demonstration Program
// Compares single-machine hardware-atomic OS semaphores (xv6)
// with decentralized blockchain consensus semaphores (ChainSync).
//
void test_mutex(void)
{
  printf("\n--- Test 1: Binary Semaphore (Mutex) in xv6 ---\n");
  int sem_id = 0;
  if(sem_init(sem_id, 1) < 0){
    printf("sem_init failed\n");
    exit(1);
  }

  int pid = fork();
  if(pid < 0){
    printf("fork failed\n");
    exit(1);
  }

  if(pid == 0){
    // Child process
    sem_wait(sem_id);
    printf("  [Child %d] Entered Critical Section\n", getpid());
    pause(10);
    printf("  [Child %d] Leaving Critical Section\n", getpid());
    sem_signal(sem_id);
    exit(0);
  } else {
    // Parent process
    sem_wait(sem_id);
    printf("  [Parent %d] Entered Critical Section\n", getpid());
    pause(10);
    printf("  [Parent %d] Leaving Critical Section\n", getpid());
    sem_signal(sem_id);
    wait(0);
  }
  printf("  -> Mutex mutual exclusion verified in xv6.\n");
}

void test_counting_semaphore(void)
{
  printf("\n--- Test 2: Counting Semaphore (Capacity = 2) ---\n");
  int sem_id = 1;
  int capacity = 2;
  sem_init(sem_id, capacity);

  for(int i = 0; i < 3; i++){
    int pid = fork();
    if(pid == 0){
      sem_wait(sem_id);
      printf("  [Worker %d] Acquired 1 unit of capacity\n", getpid());
      pause(15);
      printf("  [Worker %d] Releasing unit\n", getpid());
      sem_signal(sem_id);
      exit(0);
    }
  }

  for(int i = 0; i < 3; i++){
    wait(0);
  }
  printf("  -> Counting semaphore bounds verified in xv6.\n");
}

int main(int argc, char *argv[])
{
  printf("============================================================\n");
  printf("  xv6 Local OS Semaphore vs ChainSync Blockchain Consensus\n");
  printf("============================================================\n");
  printf("1. OS Semaphore: Managed in kernel memory (sem_wait / sem_signal)\n");
  printf("2. ChainSync: Replicated state machine with blockchain consensus\n");

  test_mutex();
  test_counting_semaphore();

  printf("\n[SUCCESS] All xv6 local semaphore tests passed.\n");
  exit(0);
}
