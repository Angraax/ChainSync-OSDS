#include "types.h"
#include "riscv.h"
#include "defs.h"
#include "param.h"
#include "spinlock.h"

#define MAX_SEMAPHORES 16

struct semaphore {
  struct spinlock lock;
  int value;
  int active;
};

static struct semaphore semaphores[MAX_SEMAPHORES];

void
sem_init_system(void)
{
  for(int i = 0; i < MAX_SEMAPHORES; i++){
    initlock(&semaphores[i].lock, "semaphore");
    semaphores[i].value = 0;
    semaphores[i].active = 0;
  }
}

int
ksem_init(int sem_id, int init_val)
{
  if(sem_id < 0 || sem_id >= MAX_SEMAPHORES || init_val < 0)
    return -1;
  acquire(&semaphores[sem_id].lock);
  semaphores[sem_id].value = init_val;
  semaphores[sem_id].active = 1;
  release(&semaphores[sem_id].lock);
  return 0;
}

int
ksem_wait(int sem_id)
{
  if(sem_id < 0 || sem_id >= MAX_SEMAPHORES)
    return -1;
  struct semaphore *s = &semaphores[sem_id];
  acquire(&s->lock);
  if(!s->active){
    release(&s->lock);
    return -1;
  }
  while(s->value <= 0){
    sleep(s, &s->lock);
  }
  s->value--;
  release(&s->lock);
  return 0;
}

int
ksem_signal(int sem_id)
{
  if(sem_id < 0 || sem_id >= MAX_SEMAPHORES)
    return -1;
  struct semaphore *s = &semaphores[sem_id];
  acquire(&s->lock);
  if(!s->active){
    release(&s->lock);
    return -1;
  }
  s->value++;
  wakeup(s);
  release(&s->lock);
  return 0;
}
