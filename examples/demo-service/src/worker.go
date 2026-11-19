package main

import (
	"fmt"
	"os"
)

func main() {
	token := os.Getenv("GITHUB_TOKEN")
	workers, ok := os.LookupEnv("WORKER_CONCURRENCY")
	fmt.Println(token, workers, ok)
}
