package com.skala.fab.domain.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "transport_time")
public class TransportTimeEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    @Column(name = "from_loc")
    private String fromLoc;
    @Column(name = "to_loc")
    private String toLoc;
    private String distType;
    private Double meanTime;
    private Double offsetTime;
    private String timeUnit;
}
