package com.skala.fab.domain.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "active_cqt_timer")
public class ActiveCqtTimerEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String lotId;
    private Integer startStep;
    private Integer targetStep;
    private Double deadlineTime;
    private Double startedAt;
    private Boolean isActive;
}
