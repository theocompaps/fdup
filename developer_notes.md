# Developer Notes

This is the developer notes containing future features, idea etc.

## Other Work

A short search on github reveals that many has tried to implement the same in many different languages etc.

One of interest is:

https://github.com/rck/fdup

Which claims to be fast. It looks like the core algorithm is the same as the one used in this implementation.

It also contains a table with some speed testing:

| Program  | user    | system | cpu (%) | total   |
| -------- | ------- | ------ | ------- | ------- |
| fdup     | 3.38s   | 6.10s  | 5       | 3:01.89 |
| fslint   | 18.04s  | 9.20s  | 12      | 3:41.20 |
| fdupes   | 62.35s  | 15.46s | 20      | 6:16.49 |
| duff     | 22.59s  | 4.42s  | 6       | 7:18.13 |
| dupseek  | 18.33s  | 6.55s  | 4       | 8:30.35 |
| ftwin    | 15.94s  | 7.50s  | 3       | 9:57.91 |

## Future Features

* Output to eFlow
* Output as Linux commands
* GUI support in PyQT
* Support for running find and md5 in parallel threads
